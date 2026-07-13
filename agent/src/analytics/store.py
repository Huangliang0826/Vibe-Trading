from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from src.config.paths import get_runtime_root

from .models import AnalyticsEvent, MetricPoint, SourceSyncState


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class AnalyticsStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else get_runtime_root() / "analytics.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw_events (
                    event_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT,
                    feature TEXT NOT NULL,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    duration_ms INTEGER,
                    app_version TEXT,
                    commit_sha TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_raw_events_kind_time
                    ON raw_events(kind, occurred_at);
                CREATE INDEX IF NOT EXISTS idx_raw_events_feature_time
                    ON raw_events(feature, occurred_at);

                CREATE TABLE IF NOT EXISTS metric_points (
                    bucket TEXT NOT NULL,
                    granularity TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    dimensions_json TEXT NOT NULL,
                    value REAL,
                    numerator REAL,
                    denominator REAL,
                    sample_count INTEGER NOT NULL,
                    interval_low REAL,
                    interval_high REAL,
                    calculation_version TEXT NOT NULL,
                    PRIMARY KEY (
                        bucket, granularity, domain, metric,
                        dimensions_json, calculation_version
                    )
                );
                CREATE INDEX IF NOT EXISTS idx_metric_points_lookup
                    ON metric_points(metric, granularity, bucket);

                CREATE TABLE IF NOT EXISTS source_sync_state (
                    source TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    last_attempted_at TEXT NOT NULL,
                    last_success_at TEXT,
                    data_through TEXT,
                    records_scanned INTEGER NOT NULL,
                    events_written INTEGER NOT NULL,
                    coverage_days INTEGER NOT NULL,
                    reason TEXT
                );
                PRAGMA user_version=2;
                """
            )

    def append_events(self, events: list[AnalyticsEvent]) -> int:
        if not events:
            return 0
        rows = [
            (
                event.event_id,
                event.kind,
                _utc_iso(event.occurred_at),
                event.workspace_id,
                event.user_id,
                event.session_id,
                event.feature,
                event.action,
                event.outcome,
                event.duration_ms,
                event.app_version,
                event.commit_sha,
                _canonical_json(event.metadata),
            )
            for event in events
        ]
        with self._session() as connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT OR IGNORE INTO raw_events (
                    event_id, kind, occurred_at, workspace_id, user_id,
                    session_id, feature, action, outcome, duration_ms,
                    app_version, commit_sha, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return connection.total_changes - before

    def query_events(
        self,
        *,
        kind: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[AnalyticsEvent]:
        clauses: list[str] = []
        parameters: list[object] = []
        if kind is not None:
            clauses.append("kind = ?")
            parameters.append(kind)
        if start is not None:
            clauses.append("occurred_at >= ?")
            parameters.append(_utc_iso(start))
        if end is not None:
            clauses.append("occurred_at < ?")
            parameters.append(_utc_iso(end))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT * FROM raw_events{where} ORDER BY occurred_at, event_id",
                parameters,
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def upsert_metric_points(self, points: list[MetricPoint]) -> None:
        if not points:
            return
        rows = [
            (
                point.bucket,
                point.granularity,
                point.domain,
                point.metric,
                _canonical_json(point.dimensions),
                point.value,
                point.numerator,
                point.denominator,
                point.sample_count,
                point.interval_low,
                point.interval_high,
                point.calculation_version,
            )
            for point in points
        ]
        with self._session() as connection:
            connection.executemany(
                """
                INSERT INTO metric_points (
                    bucket, granularity, domain, metric, dimensions_json,
                    value, numerator, denominator, sample_count,
                    interval_low, interval_high, calculation_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    bucket, granularity, domain, metric,
                    dimensions_json, calculation_version
                ) DO UPDATE SET
                    value = excluded.value,
                    numerator = excluded.numerator,
                    denominator = excluded.denominator,
                    sample_count = excluded.sample_count,
                    interval_low = excluded.interval_low,
                    interval_high = excluded.interval_high
                """,
                rows,
            )

    def query_metric_points(
        self,
        *,
        metric: str | None = None,
        domain: str | None = None,
        granularity: str | None = None,
        start_bucket: str | None = None,
        end_bucket: str | None = None,
    ) -> list[MetricPoint]:
        filters = {
            "metric": metric,
            "domain": domain,
            "granularity": granularity,
        }
        clauses: list[str] = []
        parameters: list[object] = []
        for column, value in filters.items():
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        if start_bucket is not None:
            clauses.append("bucket >= ?")
            parameters.append(start_bucket)
        if end_bucket is not None:
            clauses.append("bucket <= ?")
            parameters.append(end_bucket)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._session() as connection:
            rows = connection.execute(
                f"SELECT * FROM metric_points{where} ORDER BY bucket, metric, dimensions_json",
                parameters,
            ).fetchall()
        return [self._metric_from_row(row) for row in rows]

    def upsert_source_state(self, state: SourceSyncState) -> None:
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO source_sync_state (
                    source, status, last_attempted_at, last_success_at,
                    data_through, records_scanned, events_written,
                    coverage_days, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    status = excluded.status,
                    last_attempted_at = excluded.last_attempted_at,
                    last_success_at = excluded.last_success_at,
                    data_through = excluded.data_through,
                    records_scanned = excluded.records_scanned,
                    events_written = excluded.events_written,
                    coverage_days = excluded.coverage_days,
                    reason = excluded.reason
                """,
                (
                    state.source,
                    state.status,
                    state.last_attempted_at,
                    state.last_success_at,
                    state.data_through,
                    state.records_scanned,
                    state.events_written,
                    state.coverage_days,
                    state.reason,
                ),
            )

    def get_source_states(self, source: str | None = None) -> list[SourceSyncState]:
        query = "SELECT * FROM source_sync_state"
        parameters: tuple[object, ...] = ()
        if source is not None:
            query += " WHERE source = ?"
            parameters = (source,)
        query += " ORDER BY source"
        with self._session() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._source_state_from_row(row) for row in rows]

    def prune(self, *, reference: datetime | None = None) -> dict[str, int]:
        now = reference or datetime.now(timezone.utc)
        raw_cutoff = _utc_iso(now - timedelta(days=90))
        hourly_cutoff = _utc_iso(now - timedelta(days=180))[:19]
        with self._session() as connection:
            raw = connection.execute(
                "DELETE FROM raw_events WHERE kind IN ('product', 'system') AND occurred_at < ?",
                (raw_cutoff,),
            ).rowcount
            metrics = connection.execute(
                "DELETE FROM metric_points WHERE granularity = 'hour' AND substr(bucket, 1, 19) < ?",
                (hourly_cutoff,),
            ).rowcount
        return {"raw_events": raw, "metric_points": metrics}

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> AnalyticsEvent:
        return AnalyticsEvent(
            event_id=row["event_id"],
            kind=row["kind"],
            occurred_at=datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00")),
            workspace_id=row["workspace_id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            feature=row["feature"],
            action=row["action"],
            outcome=row["outcome"],
            duration_ms=row["duration_ms"],
            app_version=row["app_version"],
            commit_sha=row["commit_sha"],
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _metric_from_row(row: sqlite3.Row) -> MetricPoint:
        return MetricPoint(
            bucket=row["bucket"],
            granularity=row["granularity"],
            domain=row["domain"],
            metric=row["metric"],
            dimensions=json.loads(row["dimensions_json"]),
            value=row["value"],
            numerator=row["numerator"],
            denominator=row["denominator"],
            sample_count=row["sample_count"],
            interval_low=row["interval_low"],
            interval_high=row["interval_high"],
            calculation_version=row["calculation_version"],
        )

    @staticmethod
    def _source_state_from_row(row: sqlite3.Row) -> SourceSyncState:
        return SourceSyncState(
            source=row["source"],
            status=row["status"],
            last_attempted_at=row["last_attempted_at"],
            last_success_at=row["last_success_at"],
            data_through=row["data_through"],
            records_scanned=row["records_scanned"],
            events_written=row["events_written"],
            coverage_days=row["coverage_days"],
            reason=row["reason"],
        )
