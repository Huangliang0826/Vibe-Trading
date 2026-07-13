from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .collector import AnalyticsCollector
from .rollup import CALCULATION_VERSION, AnalyticsRollup
from .store import AnalyticsStore


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class AnalyticsService:
    def __init__(
        self,
        store: AnalyticsStore,
        collector: AnalyticsCollector,
        rollup: AnalyticsRollup,
    ) -> None:
        self.store = store
        self.collector = collector
        self.rollup = rollup

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
