import asyncio
import sqlite3

from src.analytics.collector import AnalyticsCollector
from src.analytics.rollup import AnalyticsRollup
from src.analytics.runtime import AnalyticsRuntime
from src.analytics.store import AnalyticsStore
from tests.analytics.test_store import _event


class FailingStore(AnalyticsStore):
    def append_events(self, events):
        raise sqlite3.OperationalError("locked")


def test_runtime_isolates_flush_failure(tmp_path):
    store = FailingStore(tmp_path / "a.db")
    collector = AnalyticsCollector(store)
    collector.submit(_event())
    runtime = AnalyticsRuntime(collector, AnalyticsRollup(store), poll_seconds=0.01)
    assert asyncio.run(runtime.flush_once()) == 0


def test_runtime_stops_cleanly(tmp_path):
    async def scenario():
        store = AnalyticsStore(tmp_path / "a.db")
        runtime = AnalyticsRuntime(AnalyticsCollector(store), AnalyticsRollup(store), poll_seconds=0.01)
        runtime.start()
        await asyncio.sleep(0.02)
        await runtime.stop()
        assert runtime.task is None

    asyncio.run(scenario())
