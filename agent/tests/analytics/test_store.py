from datetime import datetime, timedelta, timezone

from src.analytics.models import AnalyticsEvent, MetricPoint
from src.analytics.store import AnalyticsStore


def _event(event_id: str = "evt-1") -> AnalyticsEvent:
    return AnalyticsEvent(
        event_id=event_id,
        kind="product",
        occurred_at=datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc),
        workspace_id="local",
        user_id="user-hash",
        feature="scanner",
        action="result_view",
        outcome="success",
        duration_ms=120,
        metadata={"route": "/scanner"},
    )


def test_append_deduplicates_event_id(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    assert store.append_events([_event()]) == 1
    assert store.append_events([_event()]) == 0
    assert [row.event_id for row in store.query_events(kind="product")] == ["evt-1"]


def test_metric_point_preserves_sample_and_interval(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    point = MetricPoint(
        bucket="2026-07-13",
        granularity="day",
        domain="usage",
        metric="result_view_rate",
        dimensions={"feature": "scanner"},
        value=0.75,
        numerator=3,
        denominator=4,
        sample_count=4,
        interval_low=0.30,
        interval_high=0.95,
        calculation_version="analytics.v1",
    )
    store.upsert_metric_points([point])
    assert store.query_metric_points(metric="result_view_rate")[0] == point


def test_prune_applies_raw_and_hourly_retention_without_deleting_daily(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    old = now - timedelta(days=200)
    store.append_events(
        [
            _event("old-product").model_copy(update={"occurred_at": old}),
            _event("old-quality").model_copy(update={"occurred_at": old, "kind": "quality"}),
            _event("current").model_copy(update={"occurred_at": now}),
        ]
    )
    base = MetricPoint(
        bucket=old.isoformat(), granularity="hour", domain="usage", metric="page_views",
        value=1, sample_count=1, calculation_version="analytics.v1",
    )
    store.upsert_metric_points(
        [base, base.model_copy(update={"bucket": old.date().isoformat(), "granularity": "day"})]
    )

    assert store.prune(reference=now) == {"raw_events": 1, "metric_points": 1}
    assert {event.event_id for event in store.query_events()} == {"old-quality", "current"}
    assert [point.granularity for point in store.query_metric_points()] == ["day"]
