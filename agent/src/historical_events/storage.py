from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.historical_events.models import HistoricalEvent, HistoricalEventRun


class HistoricalEventStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".vibe-trading" / "historical_events.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits/rolls back and then always closes.

        A bare ``with self._connect()`` only manages the transaction, leaking
        the connection's file descriptors on every call.
        """
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._session() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS historical_events (
                    event_id TEXT NOT NULL,
                    detector_version TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    market TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (event_id, detector_version, analysis_version)
                );
                CREATE INDEX IF NOT EXISTS idx_historical_events_range
                ON historical_events (market, symbol, start_date, end_date);
                CREATE TABLE IF NOT EXISTS historical_event_runs (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def save_event(self, event: HistoricalEvent) -> HistoricalEvent:
        with self._session() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO historical_events
                (event_id, detector_version, analysis_version, market, symbol, start_date, end_date, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id, event.detector_version, event.analysis_version,
                    event.market, event.symbol, event.start_date.isoformat(), event.end_date.isoformat(),
                    event.model_dump_json(),
                ),
            )
        return event

    def list_events(
        self, market: str, symbol: str, start_date: str, end_date: str,
        analysis_version: str | None = None,
    ) -> list[HistoricalEvent]:
        version_clause = " AND analysis_version = ?" if analysis_version else ""
        params: tuple[str, ...] = (market, symbol, start_date, end_date)
        if analysis_version:
            params += (analysis_version,)
        with self._session() as db:
            rows = db.execute(
                f"""
                SELECT payload_json FROM historical_events
                WHERE market = ? AND symbol = ? AND end_date >= ? AND start_date <= ?
                {version_clause}
                ORDER BY start_date DESC
                """,
                params,
            ).fetchall()
        return [HistoricalEvent.model_validate_json(row["payload_json"]) for row in rows]

    def save_run(self, run: HistoricalEventRun) -> HistoricalEventRun:
        with self._session() as db:
            db.execute(
                "INSERT OR REPLACE INTO historical_event_runs (run_id, payload_json) VALUES (?, ?)",
                (run.run_id, run.model_dump_json()),
            )
        return run

    def get_run(self, run_id: str) -> HistoricalEventRun | None:
        with self._session() as db:
            row = db.execute(
                "SELECT payload_json FROM historical_event_runs WHERE run_id = ?", (run_id,),
            ).fetchone()
        return HistoricalEventRun.model_validate_json(row["payload_json"]) if row else None

    def find_completed_run(
        self, market: str, symbol: str, period: str, analysis_version: str,
    ) -> HistoricalEventRun | None:
        with self._session() as db:
            rows = db.execute("SELECT payload_json FROM historical_event_runs").fetchall()
        matches = [HistoricalEventRun.model_validate_json(row["payload_json"]) for row in rows]
        matches = [
            run for run in matches
            if run.market == market and run.symbol == symbol and run.period == period
            and run.status == "completed" and run.analysis_version == analysis_version
        ]
        return max(matches, key=lambda run: run.updated_at, default=None)
