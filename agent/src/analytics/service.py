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


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        response = self._response(points, days=days)
        response["funnel"] = self._session_funnel(days)
        return response

    def system_health(self, days: int) -> dict[str, Any]:
        system = self._points(days=days, domain="system")
        data = self._points(days=days, domain="data")
        return self._response([*system, *data], days=days)

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
        return {
            "data_through": latest["bucket"] if latest else None,
            "generated_at": _iso_now(),
            "sample_count": sum(point["sample_count"] for point in series),
            "calculation_version": CALCULATION_VERSION,
            "warnings": [status] if status != "available" else [],
            "days": days,
            "status": status,
            "value": available[-1]["value"] if available else None,
            "series": series,
        }

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
    def _response(points: list, *, days: int) -> dict[str, Any]:
        return {
            "data_through": max((point.bucket for point in points), default=None),
            "generated_at": _iso_now(),
            "sample_count": sum(point.sample_count for point in points),
            "calculation_version": CALCULATION_VERSION,
            "warnings": [] if points else ["no_data"],
            "days": days,
            "points": [point.model_dump(mode="json") for point in points],
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
