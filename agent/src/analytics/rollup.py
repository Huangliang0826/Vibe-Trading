from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

from .models import AnalyticsEvent, MetricPoint
from .statistics import wilson_interval
from .store import AnalyticsStore

CALCULATION_VERSION = "analytics.v1"

USAGE_METRICS = (
    "page_views",
    "task_starts",
    "task_completions",
    "task_success_rate",
    "result_views",
    "result_view_rate",
    "research_sessions",
    "effective_research_sessions",
    "effective_session_rate",
    "time_to_insight_p50_ms",
    "time_to_insight_p95_ms",
)
SYSTEM_METRICS = (
    "request_count",
    "request_success_rate",
    "duration_p50_ms",
    "duration_p95_ms",
    "timeout_count",
    "data_freshness_p95_ms",
)
DATA_METRICS = ("freshness_compliance_rate", "completeness_rate")


def _nearest_rank(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _count_point(
    bucket: str,
    domain: str,
    metric: str,
    dimensions: dict[str, str],
    value: int,
) -> MetricPoint:
    return MetricPoint(
        bucket=bucket,
        granularity="day",
        domain=domain,
        metric=metric,
        dimensions=dimensions,
        value=float(value),
        sample_count=value,
        calculation_version=CALCULATION_VERSION,
    )


def _value_point(
    bucket: str,
    domain: str,
    metric: str,
    dimensions: dict[str, str],
    value: float | None,
    sample_count: int,
) -> MetricPoint:
    return MetricPoint(
        bucket=bucket,
        granularity="day",
        domain=domain,
        metric=metric,
        dimensions=dimensions,
        value=value,
        sample_count=sample_count,
        calculation_version=CALCULATION_VERSION,
    )


def _ratio_point(
    bucket: str,
    domain: str,
    metric: str,
    dimensions: dict[str, str],
    numerator: float,
    denominator: float,
    sample_count: int,
) -> MetricPoint:
    if denominator <= 0:
        value = low = high = None
    else:
        value = numerator / denominator
        low, high = wilson_interval(numerator, denominator)
    return MetricPoint(
        bucket=bucket,
        granularity="day",
        domain=domain,
        metric=metric,
        dimensions=dimensions,
        value=value,
        numerator=numerator,
        denominator=denominator,
        sample_count=sample_count,
        interval_low=low,
        interval_high=high,
        calculation_version=CALCULATION_VERSION,
    )


class AnalyticsRollup:
    def __init__(self, store: AnalyticsStore) -> None:
        self.store = store

    def run_day(self, day: date) -> list[MetricPoint]:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        events = self.store.query_events(start=start, end=end)
        bucket = day.isoformat()
        points = [
            *self._usage_points(bucket, [event for event in events if event.kind == "product"]),
            *self._system_points(bucket, [event for event in events if event.kind == "system"]),
        ]
        self.store.upsert_metric_points(points)
        return points

    def run_missing_days(self, *, through: date | None = None, lookback_days: int = 2) -> list[MetricPoint]:
        last_day = through or datetime.now(timezone.utc).date()
        points: list[MetricPoint] = []
        for offset in range(max(1, lookback_days)):
            points.extend(self.run_day(last_day - timedelta(days=offset)))
        return points

    @staticmethod
    def _usage_points(bucket: str, events: list[AnalyticsEvent]) -> list[MetricPoint]:
        grouped: dict[str, list[AnalyticsEvent]] = defaultdict(list)
        for event in events:
            grouped[event.feature].append(event)
        points: list[MetricPoint] = []
        for feature, feature_events in grouped.items():
            dimensions = {"feature": feature}
            actions: dict[str, list[AnalyticsEvent]] = defaultdict(list)
            for event in feature_events:
                actions[event.action].append(event)
            page_views = len(actions["page_view"])
            starts = len(actions["task_start"])
            completions = actions["task_complete"]
            successful = sum(event.outcome == "success" for event in completions)
            result_views = len(actions["result_view"])
            points.extend(
                [
                    _count_point(bucket, "usage", "page_views", dimensions, page_views),
                    _count_point(bucket, "usage", "task_starts", dimensions, starts),
                    _count_point(bucket, "usage", "task_completions", dimensions, len(completions)),
                    _ratio_point(
                        bucket,
                        "usage",
                        "task_success_rate",
                        dimensions,
                        successful,
                        len(completions),
                        len(completions),
                    ),
                    _count_point(bucket, "usage", "result_views", dimensions, result_views),
                    _ratio_point(
                        bucket,
                        "usage",
                        "result_view_rate",
                        dimensions,
                        result_views,
                        len(completions),
                        len(completions),
                    ),
                ]
            )

            sessions: dict[str, list[AnalyticsEvent]] = defaultdict(list)
            for event in feature_events:
                if event.session_id:
                    sessions[event.session_id].append(event)
            research_sessions = {
                session_id
                for session_id, session_events in sessions.items()
                if any(event.action == "task_start" for event in session_events)
            }
            effective_sessions: set[str] = set()
            insight_durations: list[float] = []
            for session_id in research_sessions:
                ordered = sorted(sessions[session_id], key=lambda event: event.occurred_at)
                successful_completions = [
                    event
                    for event in ordered
                    if event.action == "task_complete" and event.outcome == "success"
                ]
                result_events = [event for event in ordered if event.action == "result_view"]
                if any(
                    result.occurred_at > completion.occurred_at
                    for completion in successful_completions
                    for result in result_events
                ):
                    effective_sessions.add(session_id)
                starts_in_session = [event for event in ordered if event.action == "task_start"]
                if starts_in_session and result_events:
                    first_start = starts_in_session[0]
                    later_results = [
                        event for event in result_events if event.occurred_at >= first_start.occurred_at
                    ]
                    if later_results:
                        insight_durations.append(
                            (later_results[0].occurred_at - first_start.occurred_at).total_seconds() * 1000
                        )
            points.extend(
                [
                    _count_point(
                        bucket, "usage", "research_sessions", dimensions, len(research_sessions)
                    ),
                    _count_point(
                        bucket,
                        "usage",
                        "effective_research_sessions",
                        dimensions,
                        len(effective_sessions),
                    ),
                    _ratio_point(
                        bucket,
                        "usage",
                        "effective_session_rate",
                        dimensions,
                        len(effective_sessions),
                        len(research_sessions),
                        len(research_sessions),
                    ),
                    _value_point(
                        bucket,
                        "usage",
                        "time_to_insight_p50_ms",
                        dimensions,
                        _nearest_rank(insight_durations, 0.50),
                        len(insight_durations),
                    ),
                    _value_point(
                        bucket,
                        "usage",
                        "time_to_insight_p95_ms",
                        dimensions,
                        _nearest_rank(insight_durations, 0.95),
                        len(insight_durations),
                    ),
                ]
            )
        return points

    @staticmethod
    def _system_points(bucket: str, events: list[AnalyticsEvent]) -> list[MetricPoint]:
        route_groups: dict[str, list[AnalyticsEvent]] = defaultdict(list)
        data_groups: dict[tuple[str, str], list[AnalyticsEvent]] = defaultdict(list)
        for event in events:
            route = str(event.metadata.get("route") or event.feature)
            route_groups[route].append(event)
            provider = str(event.metadata.get("provider") or "unknown")
            market = str(event.metadata.get("market") or "unknown")
            data_groups[(provider, market)].append(event)

        points: list[MetricPoint] = []
        for route, route_events in route_groups.items():
            dimensions = {"route": route}
            successes = sum(event.outcome == "success" for event in route_events)
            durations = [event.duration_ms for event in route_events if event.duration_ms is not None]
            timeouts = sum(
                event.action == "timeout" or event.metadata.get("error_code") == "timeout"
                for event in route_events
            )
            freshness = [
                float(event.metadata["data_freshness_ms"])
                for event in route_events
                if isinstance(event.metadata.get("data_freshness_ms"), (int, float))
            ]
            points.extend(
                [
                    _count_point(bucket, "system", "request_count", dimensions, len(route_events)),
                    _ratio_point(
                        bucket,
                        "system",
                        "request_success_rate",
                        dimensions,
                        successes,
                        len(route_events),
                        len(route_events),
                    ),
                    _value_point(
                        bucket,
                        "system",
                        "duration_p50_ms",
                        dimensions,
                        _nearest_rank(durations, 0.50),
                        len(durations),
                    ),
                    _value_point(
                        bucket,
                        "system",
                        "duration_p95_ms",
                        dimensions,
                        _nearest_rank(durations, 0.95),
                        len(durations),
                    ),
                    _count_point(bucket, "system", "timeout_count", dimensions, timeouts),
                    _value_point(
                        bucket,
                        "system",
                        "data_freshness_p95_ms",
                        dimensions,
                        _nearest_rank(freshness, 0.95),
                        len(freshness),
                    ),
                ]
            )

        for (provider, market), data_events in data_groups.items():
            dimensions = {"market": market, "provider": provider}
            freshness_observations = [
                event
                for event in data_events
                if isinstance(event.metadata.get("data_freshness_ms"), (int, float))
                and isinstance(event.metadata.get("freshness_slo_ms"), (int, float))
            ]
            compliant = sum(
                float(event.metadata["data_freshness_ms"])
                <= float(event.metadata["freshness_slo_ms"])
                for event in freshness_observations
            )
            completeness_observations = [
                event
                for event in data_events
                if isinstance(event.metadata.get("expected_count"), (int, float))
                and float(event.metadata["expected_count"]) > 0
                and isinstance(event.metadata.get("observed_count"), (int, float))
            ]
            observed = sum(float(event.metadata["observed_count"]) for event in completeness_observations)
            expected = sum(float(event.metadata["expected_count"]) for event in completeness_observations)
            points.extend(
                [
                    _ratio_point(
                        bucket,
                        "data",
                        "freshness_compliance_rate",
                        dimensions,
                        compliant,
                        len(freshness_observations),
                        len(freshness_observations),
                    ),
                    _ratio_point(
                        bucket,
                        "data",
                        "completeness_rate",
                        dimensions,
                        observed,
                        expected,
                        len(completeness_observations),
                    ),
                ]
            )
        return points
