from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from pathlib import Path
from dataclasses import asdict

from .collector import AnalyticsCollector
from .rollup import CALCULATION_VERSION, AnalyticsRollup
from .store import AnalyticsStore
from .statistics import wilson_interval
from .git_activity import GitActivityReader
from .development import group_commits, rank_module_churn
from .edge import EDGE_SPECS, EdgeSpec, evaluate_edge, pool_rate


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _freshness(data_through: str | None, *, source_error: bool = False) -> str:
    if data_through is None:
        return "no_data"
    try:
        observed = datetime.fromisoformat(data_through[:10]).date()
    except ValueError:
        return "stale"
    if source_error or (datetime.now(timezone.utc).date() - observed).days > 2:
        return "stale"
    return "fresh"


def _coverage(
    *,
    days: int,
    buckets: set[str],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    covered_days = len(buckets)
    return {
        "window_days": days,
        "covered_days": covered_days,
        "coverage_rate": covered_days / days,
        "sources": sources,
    }


class AnalyticsService:
    def __init__(
        self,
        store: AnalyticsStore,
        collector: AnalyticsCollector,
        rollup: AnalyticsRollup,
        git_reader: GitActivityReader | None = None,
    ) -> None:
        self.store = store
        self.collector = collector
        self.rollup = rollup
        self.git_reader = git_reader or GitActivityReader(Path(__file__).resolve().parents[3])

    def trends(self, metric: str, days: int) -> dict[str, Any]:
        points = self._points(days=days, metric=metric)
        return self._response(points, days=days)

    def usage(self, days: int) -> dict[str, Any]:
        points = self._points(days=days, domain="usage")
        response = self._response(points, days=days, source="product_events")
        response["funnel"] = self._session_funnel(days)
        return response

    def system_health(self, days: int) -> dict[str, Any]:
        system = self._points(days=days, domain="system")
        data = self._points(days=days, domain="data")
        return self._response([*system, *data], days=days, source="system_events")

    def research_quality(
        self,
        *,
        days: int,
        subject: str,
        market: str | None,
        horizon: str | None,
        regime: str | None,
    ) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        events = self.store.query_events(kind="quality", start=start, end=end)
        filtered = [event for event in events if event.metadata.get("subject_type") == subject]
        if market:
            filtered = [event for event in filtered if event.metadata.get("market") == market]
        if horizon:
            filtered = [event for event in filtered if event.metadata.get("horizon") == horizon]
        if regime:
            filtered = [event for event in filtered if event.metadata.get("regime") == regime]
        rate_metrics = {"hit_rate", "directional_accuracy", "interval_coverage_80"}
        series: list[dict[str, Any]] = []
        for event in filtered:
            metadata = event.metadata
            sample_count = int(metadata.get("sample_count") or 0)
            metric = str(metadata.get("metric_name") or event.action)
            value = metadata.get("metric_value")
            low = metadata.get("interval_low")
            high = metadata.get("interval_high")
            reason = metadata.get("reason")
            if sample_count < 20:
                value = None
                reason = "insufficient_sample"
            elif metric in rate_metrics and value is not None and (low is None or high is None):
                low, high = wilson_interval(round(float(value) * sample_count), sample_count)
            series.append({
                "bucket": str(metadata.get("as_of") or event.occurred_at.date().isoformat()),
                "subject": metadata.get("subject_type"),
                "subject_id": metadata.get("subject_id"),
                "market": metadata.get("market"),
                "horizon": metadata.get("horizon"),
                "regime": metadata.get("regime"),
                "metric": metric,
                "value": value,
                "sample_count": sample_count,
                "interval_low": low,
                "interval_high": high,
                "formula_version": metadata.get("formula_version"),
                "reason": reason,
            })
        series.sort(key=lambda point: (point["bucket"], point["metric"], str(point["subject_id"])))
        latest = series[-1] if series else None
        available = [point for point in series if point["value"] is not None]
        status = "available" if available else ("insufficient_sample" if series else "no_data")
        source_states = self.store.get_source_states(subject)
        freshness = _freshness(
            latest["bucket"] if latest else None,
            source_error=any(state.status == "error" for state in source_states),
        )
        warnings = [status] if status != "available" else []
        if freshness == "stale":
            warnings.append("stale_data")
        return {
            "data_through": latest["bucket"] if latest else None,
            "generated_at": _iso_now(),
            "sample_count": sum(point["sample_count"] for point in series),
            "calculation_version": CALCULATION_VERSION,
            "warnings": warnings,
            "days": days,
            "status": status,
            "value": available[-1]["value"] if available else None,
            "series": series,
            "freshness": freshness,
            "coverage": _coverage(
                days=days,
                buckets={point["bucket"] for point in series},
                sources=[state.model_dump(mode="json") for state in source_states],
            ),
        }

    def edge_scorecard(self, *, days: int, cost_bps: float = 15.0) -> dict[str, Any]:
        """Per-signal-source verdict: after costs, vs a do-nothing baseline —
        does each source demonstrate an edge, and how confident are we?"""
        today = datetime.now(timezone.utc).date()
        start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        events = self.store.query_events(kind="quality", start=start, end=end)

        rows: list[dict[str, Any]] = []
        for subject, spec in EDGE_SPECS.items():
            metric_events = [
                e for e in events
                if e.metadata.get("subject_type") == subject
                and e.metadata.get("metric_name") == spec.metric
            ]
            if not metric_events:
                continue
            error_sources = any(s.status == "error" for s in self.store.get_source_states(subject))
            if subject == "forecast":
                rows.extend(self._forecast_rows(metric_events, spec, cost_bps, error_sources))
            else:
                rows.extend(self._grouped_rows(subject, metric_events, spec, cost_bps, error_sources))

        # Sort: edges first, then no_edge, then insufficient; strongest sample first.
        order = {"edge": 0, "no_edge": 1, "insufficient": 2}
        rows.sort(key=lambda r: (order.get(r["verdict"], 3), -(r["sample_count"] or 0)))
        summary = {
            "edge": sum(1 for r in rows if r["verdict"] == "edge"),
            "no_edge": sum(1 for r in rows if r["verdict"] == "no_edge"),
            "insufficient": sum(1 for r in rows if r["verdict"] == "insufficient"),
        }
        return {
            "generated_at": _iso_now(),
            "calculation_version": CALCULATION_VERSION,
            "days": days,
            "cost_bps": cost_bps,
            "summary": summary,
            "rows": rows,
        }

    def _latest_by_group(self, events: list[Any], key) -> dict[Any, Any]:
        latest: dict[Any, Any] = {}
        for e in events:
            k = key(e)
            prev = latest.get(k)
            if prev is None or str(e.metadata.get("as_of") or "") >= str(prev.metadata.get("as_of") or ""):
                latest[k] = e
        return latest

    def _row(self, *, subject: str, spec: EdgeSpec, market: str, horizon: str, subject_id: str,
             value, low, high, sample_count: int, as_of: str | None, cost_bps: float,
             error_sources: bool) -> dict[str, Any]:
        a = evaluate_edge(spec, value=value, interval_low=low, interval_high=high,
                          sample_count=sample_count, cost_bps=cost_bps)
        return {
            "id": f"{subject}:{market}:{horizon}:{subject_id}",
            "source": subject,
            "market": market,
            "horizon": horizon,
            "subject_id": subject_id,
            "metric": spec.metric,
            "metric_label": spec.label,
            "unit": spec.unit,
            "baseline": spec.baseline,
            "gross_value": value,
            "value": a.net_value,
            "cost_applied": a.cost_applied,
            "interval_low": a.net_low,
            "interval_high": a.net_high,
            "sample_count": sample_count,
            "verdict": a.verdict,
            "confidence": a.confidence,
            "data_through": as_of,
            "freshness": _freshness(as_of, source_error=error_sources),
        }

    def _grouped_rows(self, subject: str, events: list[Any], spec: EdgeSpec,
                      cost_bps: float, error_sources: bool) -> list[dict[str, Any]]:
        latest = self._latest_by_group(
            events,
            lambda e: (e.metadata.get("market"), e.metadata.get("horizon"), e.metadata.get("subject_id")),
        )
        out = []
        for (market, horizon, subject_id), e in latest.items():
            m = e.metadata
            out.append(self._row(
                subject=subject, spec=spec, market=str(market), horizon=str(horizon),
                subject_id=str(subject_id), value=m.get("metric_value"),
                low=m.get("interval_low"), high=m.get("interval_high"),
                sample_count=int(m.get("sample_count") or 0),
                as_of=str(m.get("as_of")) if m.get("as_of") else None,
                cost_bps=cost_bps, error_sources=error_sources,
            ))
        return out

    def _forecast_rows(self, events: list[Any], spec: EdgeSpec,
                       cost_bps: float, error_sources: bool) -> list[dict[str, Any]]:
        # Pool per-stock directional accuracy into one number per market/horizon.
        latest = self._latest_by_group(
            events,
            lambda e: (e.metadata.get("market"), e.metadata.get("horizon"), e.metadata.get("subject_id")),
        )
        groups: dict[tuple[str, str], list[Any]] = {}
        for (market, horizon, _sid), e in latest.items():
            groups.setdefault((str(market), str(horizon)), []).append(e)
        out = []
        for (market, horizon), evs in groups.items():
            pairs = [
                (float(e.metadata["metric_value"]), int(e.metadata.get("sample_count") or 0))
                for e in evs if e.metadata.get("metric_value") is not None
            ]
            rate, total_n, low, high = pool_rate(pairs)
            as_of = max((str(e.metadata.get("as_of") or "") for e in evs), default="") or None
            out.append(self._row(
                subject="forecast", spec=spec, market=market, horizon=horizon,
                subject_id="pooled", value=rate, low=low, high=high, sample_count=total_n,
                as_of=as_of, cost_bps=cost_bps, error_sources=error_sources,
            ))
        return out

    def development(
        self,
        *,
        days: int,
        release: str | None = None,
        window_days: int = 7,
    ) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        activity = self.git_reader.read(since=since)
        commits = activity.commits
        groups = group_commits(commits)
        comparison = self._release_comparison(activity.releases, release, window_days)
        return {
            "data_through": commits[0].authored_at if commits else None,
            "generated_at": _iso_now(),
            "sample_count": len(commits),
            "calculation_version": CALCULATION_VERSION,
            "warnings": activity.warnings + (["no_data"] if not commits else []),
            "days": days,
            "commits": [asdict(commit) for commit in commits],
            "feature_groups": [asdict(group) for group in groups],
            "module_churn": rank_module_churn(commits, days),
            "releases": [asdict(item) for item in activity.releases],
            "release_comparison": comparison,
        }

    def _release_comparison(self, releases, tag: str | None, window_days: int) -> dict[str, Any] | None:
        if not tag:
            return None
        release = next((item for item in releases if item.tag == tag), None)
        if release is None:
            return {"status": "release_not_found", "tag": tag, "metrics": [], "causal": False, "disclaimer": "时间相关性，不代表该版本造成了指标变化。"}
        released = datetime.fromisoformat(release.created_at.replace("Z", "+00:00")).date()
        before_start = (released - timedelta(days=window_days)).isoformat()
        before_end = (released - timedelta(days=1)).isoformat()
        after_start = released.isoformat()
        after_end = (released + timedelta(days=window_days - 1)).isoformat()
        before = self.store.query_metric_points(granularity="day", start_bucket=before_start, end_bucket=before_end)
        after = self.store.query_metric_points(granularity="day", start_bucket=after_start, end_bucket=after_end)
        before_days = {point.bucket for point in before}
        after_days = {point.bucket for point in after}
        status = "available" if len(before_days) >= 3 and len(after_days) >= 3 else "insufficient_sample"
        metrics = []
        for metric in sorted({point.metric for point in before} & {point.metric for point in after}):
            left = [point for point in before if point.metric == metric]
            right = [point for point in after if point.metric == metric]
            def aggregate(points):
                denominator = sum(point.denominator or 0 for point in points)
                if denominator:
                    numerator = sum(point.numerator or 0 for point in points)
                    return numerator / denominator, int(denominator)
                samples = sum(point.sample_count for point in points)
                value = sum((point.value or 0) * point.sample_count for point in points) / samples if samples else None
                return value, samples
            before_value, before_sample = aggregate(left)
            after_value, after_sample = aggregate(right)
            metrics.append({"metric": metric, "before_value": before_value, "after_value": after_value, "before_sample_count": before_sample, "after_sample_count": after_sample})
        return {"status": status, "tag": tag, "window_days": window_days, "metrics": metrics if status == "available" else [], "causal": False, "disclaimer": "时间相关性，不代表该版本造成了指标变化。"}

    def _points(
        self,
        *,
        days: int,
        metric: str | None = None,
        domain: str | None = None,
    ) -> list:
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=days - 1)).isoformat()
        return self.store.query_metric_points(
            metric=metric,
            domain=domain,
            granularity="day",
            start_bucket=start,
            end_bucket=today.isoformat(),
        )

    @staticmethod
    def _response(
        points: list,
        *,
        days: int,
        source: str | None = None,
    ) -> dict[str, Any]:
        data_through = max((point.bucket for point in points), default=None)
        freshness = _freshness(data_through)
        warnings = [] if points else ["no_data"]
        if freshness == "stale":
            warnings.append("stale_data")
        buckets = {point.bucket for point in points}
        sources: list[dict[str, Any]] = []
        if source is not None and points:
            now = _iso_now()
            sources.append({
                "source": source,
                "status": "available",
                "last_attempted_at": now,
                "last_success_at": now,
                "data_through": data_through,
                "records_scanned": sum(point.sample_count for point in points),
                "events_written": 0,
                "coverage_days": len(buckets),
                "reason": None,
            })
        return {
            "data_through": data_through,
            "generated_at": _iso_now(),
            "sample_count": sum(point.sample_count for point in points),
            "calculation_version": CALCULATION_VERSION,
            "warnings": warnings,
            "days": days,
            "points": [point.model_dump(mode="json") for point in points],
            "freshness": freshness,
            "coverage": _coverage(days=days, buckets=buckets, sources=sources),
        }

    def _session_funnel(self, days: int) -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).date()
        start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        events = self.store.query_events(kind="product", start=start, end=end)
        initial = {event.session_id for event in events if event.session_id and event.action == "page_view"}
        denominator = len(initial)
        steps = (
            ("page_view", {"page_view"}),
            ("task_start", {"task_start"}),
            ("task_complete", {"task_complete"}),
            ("result_view", {"result_view"}),
            ("experiment_save_or_compare", {"experiment_save", "experiment_compare"}),
        )
        result: list[dict[str, Any]] = []
        for name, actions in steps:
            sessions = {
                event.session_id
                for event in events
                if event.session_id in initial and event.action in actions
            }
            result.append(
                {
                    "step": name,
                    "numerator": len(sessions),
                    "denominator": denominator,
                    "rate": len(sessions) / denominator if denominator else None,
                }
            )
        return result
