from datetime import date, datetime, timezone

from src.analytics.quality import make_quality_event
from src.analytics.quality_backfill import QualityBackfillCoordinator
from src.analytics.quality_sources import QualitySourceResult
from src.analytics.store import AnalyticsStore


def _quality_event(subject_id: str):
    return make_quality_event(
        subject_type="scanner",
        subject_id=subject_id,
        market="us",
        horizon="5d",
        regime="all",
        metric_name="hit_rate",
        metric_value=0.55,
        sample_count=21,
        formula_version="scanner.accuracy.v1",
        as_of=date(2026, 7, 12),
    )


class FakeSource:
    def __init__(self, source: str, events: list):
        self.source = source
        self.events = events

    def read(self, start: date, end: date):
        return QualitySourceResult(
            source=self.source,
            status="available",
            events=self.events,
            records_scanned=1,
            data_through=end.isoformat(),
            coverage_days=1,
        )


class BrokenSource:
    source = "broken"

    def read(self, start: date, end: date):
        raise OSError("fixture failure")


def test_backfill_is_idempotent_and_tracks_written_count(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    source = FakeSource("scanner", [_quality_event("q-1")])
    coordinator = QualityBackfillCoordinator(store, [source])
    reference = datetime(2026, 7, 13, tzinfo=timezone.utc)

    first = coordinator.run(reference=reference)
    second = coordinator.run(reference=reference)

    first_scanner = next(state for state in first if state.source == "scanner")
    second_scanner = next(state for state in second if state.source == "scanner")
    assert first_scanner.events_written == 1
    assert second_scanner.events_written == 0
    assert len(store.query_events(kind="quality")) == 1


def test_failed_source_does_not_block_other_sources(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    coordinator = QualityBackfillCoordinator(
        store,
        [BrokenSource(), FakeSource("backtest", [_quality_event("q-2")])],
    )

    states = coordinator.run(reference=datetime(2026, 7, 13, tzinfo=timezone.utc))

    status_by_source = {state.source: state.status for state in states}
    assert status_by_source["backtest"] == "available"
    assert status_by_source["broken"] == "error"
    assert len(store.query_events(kind="quality")) == 1


def test_backfill_reports_forecast_history_limit(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")

    states = QualityBackfillCoordinator(store, []).run(
        reference=datetime(2026, 7, 13, tzinfo=timezone.utc)
    )

    forecast = next(state for state in states if state.source == "forecast")
    assert forecast.status == "source_unavailable"
    assert forecast.reason == "no_persisted_forecast_history"
