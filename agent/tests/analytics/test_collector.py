from src.analytics.collector import AnalyticsCollector
from src.analytics.store import AnalyticsStore
from tests.analytics.test_store import _event


def test_full_queue_drops_without_raising(tmp_path):
    collector = AnalyticsCollector(AnalyticsStore(tmp_path / "a.db"), max_queue=1)
    assert collector.submit(_event("one")) is True
    assert collector.submit(_event("two")) is False
    assert collector.dropped_count == 1


def test_unknown_or_sensitive_metadata_is_rejected(tmp_path):
    collector = AnalyticsCollector(AnalyticsStore(tmp_path / "a.db"))
    assert collector.submit(_event().model_copy(update={"metadata": {"prompt": "secret"}})) is False
    assert collector.rejected_count == 1


def test_flush_persists_valid_events(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    collector = AnalyticsCollector(store)
    collector.submit(_event("one"))
    collector.submit(_event("two"))
    assert collector.flush() == 2
    assert len(store.query_events(kind="product")) == 2
