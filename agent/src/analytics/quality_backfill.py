from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .models import SourceSyncState
from .store import AnalyticsStore


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class QualityBackfillCoordinator:
    def __init__(self, store: AnalyticsStore, sources: Iterable[Any]) -> None:
        self.store = store
        self.sources = tuple(sources)

    def run(
        self,
        *,
        reference: datetime | None = None,
        lookback_days: int = 90,
    ) -> list[SourceSyncState]:
        now = reference or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        end = now.date()
        start = end - timedelta(days=max(1, lookback_days) - 1)
        attempted_at = _utc_iso(now)
        previous = {state.source: state for state in self.store.get_source_states()}
        states: list[SourceSyncState] = []

        for source in self.sources:
            source_name = str(source.source)
            prior = previous.get(source_name)
            try:
                result = source.read(start, end)
                written = self.store.append_events(result.events)
                state = SourceSyncState(
                    source=source_name,
                    status=result.status,
                    last_attempted_at=attempted_at,
                    last_success_at=attempted_at,
                    data_through=result.data_through,
                    records_scanned=result.records_scanned,
                    events_written=written,
                    coverage_days=result.coverage_days,
                    reason=result.reason,
                )
            except Exception:
                state = SourceSyncState(
                    source=source_name,
                    status="error",
                    last_attempted_at=attempted_at,
                    last_success_at=prior.last_success_at if prior else None,
                    data_through=prior.data_through if prior else None,
                    records_scanned=0,
                    events_written=0,
                    coverage_days=prior.coverage_days if prior else 0,
                    reason="source_read_failed",
                )
            self.store.upsert_source_state(state)
            states.append(state)

        states.append(self._forecast_state(start, end, attempted_at, previous.get("forecast")))
        states.sort(key=lambda state: state.source)
        return states

    def _forecast_state(
        self,
        start,
        end,
        attempted_at: str,
        prior: SourceSyncState | None,
    ) -> SourceSyncState:
        start_at = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        end_at = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        events = [
            event
            for event in self.store.query_events(kind="quality", start=start_at, end=end_at)
            if event.feature == "forecast"
        ]
        days = sorted({str(event.metadata.get("as_of") or event.occurred_at.date().isoformat()) for event in events})
        if events:
            state = SourceSyncState(
                source="forecast",
                status="available",
                last_attempted_at=attempted_at,
                last_success_at=attempted_at,
                data_through=days[-1],
                records_scanned=len(events),
                events_written=0,
                coverage_days=len(days),
            )
        else:
            state = SourceSyncState(
                source="forecast",
                status="source_unavailable",
                last_attempted_at=attempted_at,
                last_success_at=prior.last_success_at if prior else None,
                data_through=prior.data_through if prior else None,
                records_scanned=0,
                events_written=0,
                coverage_days=prior.coverage_days if prior else 0,
                reason="no_persisted_forecast_history",
            )
        self.store.upsert_source_state(state)
        return state
