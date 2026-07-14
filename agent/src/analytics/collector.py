from __future__ import annotations

import logging
import sqlite3
from queue import Empty, Full, Queue

from .models import AnalyticsEvent
from .store import AnalyticsStore

logger = logging.getLogger(__name__)

ALLOWED_METADATA = {
    "product": {"route", "market", "result_count", "source", "mode"},
    "system": {
        "route",
        "method",
        "provider",
        "market",
        "status_code",
        "error_code",
        "data_freshness_ms",
        "freshness_slo_ms",
        "expected_count",
        "observed_count",
    },
    "quality": {
        "subject_type",
        "subject_id",
        "market",
        "horizon",
        "regime",
        "metric_name",
        "metric_value",
        "sample_count",
        "interval_low",
        "interval_high",
        "formula_version",
        "as_of",
        "reason",
    },
    "development": {
        "version",
        "summary",
        "files_changed",
        "insertions",
        "deletions",
        "modules",
        "test_files_changed",
    },
}
FORBIDDEN_KEYS = {
    "prompt",
    "response",
    "api_key",
    "token",
    "authorization",
    "request_body",
    "credential",
}


class AnalyticsCollector:
    def __init__(self, store: AnalyticsStore, *, max_queue: int = 1_000) -> None:
        self.store = store
        self._queue: Queue[AnalyticsEvent] = Queue(maxsize=max_queue)
        self.dropped_count = 0
        self.rejected_count = 0

    def submit(self, event: AnalyticsEvent) -> bool:
        keys = set(event.metadata)
        if keys & FORBIDDEN_KEYS or not keys <= ALLOWED_METADATA[event.kind]:
            self.rejected_count += 1
            return False
        try:
            self._queue.put_nowait(event)
        except Full:
            self.dropped_count += 1
            return False
        return True

    def flush(self, limit: int = 100) -> int:
        drained: list[AnalyticsEvent] = []
        for _ in range(max(0, limit)):
            try:
                drained.append(self._queue.get_nowait())
            except Empty:
                break
        if not drained:
            return 0
        try:
            return self.store.append_events(drained)
        except sqlite3.Error as exc:
            self.dropped_count += len(drained)
            logger.warning(
                "analytics flush dropped %d events after %s",
                len(drained),
                type(exc).__name__,
            )
            return 0
