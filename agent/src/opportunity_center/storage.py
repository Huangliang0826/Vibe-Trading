"""SQLite persistence for opportunity-center data."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.config.paths import get_runtime_root
from src.opportunity_center.models import (
    CalibrationPeriodSummary,
    NewsArticle,
    NewsImpact,
    OpportunityCalibrationSummary,
    OpportunityDetail,
    OpportunityItem,
    OpportunityOutcome,
    RefreshJob,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    kept_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source"}
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept_query), ""))


def title_fingerprint(title: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", title.lower())
    return normalized or title.strip().lower()


def source_id_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if name.isascii():
        return slug or "source"
    digest = hashlib.sha256(name.strip().casefold().encode("utf-8")).hexdigest()[:10]
    return f"{slug or 'source'}-{digest}"


def _source_payload(source: Mapping[str, Any] | None, article: NewsArticle | None = None) -> dict[str, str]:
    if source is not None:
        name = str(source.get("name") or (article.source if article is not None else "")).strip() or "Unknown"
        source_id = str(source.get("source_id") or source_id_from_name(name))
        sector = str(source.get("sector") or "")
        url = str(source.get("url") or f"source://{source_id}")
        return {
            "source_id": source_id,
            "name": name,
            "sector": sector,
            "url": url,
        }

    if article is None:
        raise ValueError("article is required when source metadata is omitted")

    source_id = source_id_from_name(article.source)
    return {
        "source_id": source_id,
        "name": article.source,
        "sector": "",
        "url": f"source://{source_id}",
    }


def _json_loads(text: str) -> Any:
    return json.loads(text)


class OpportunityStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (get_runtime_root() / "opportunity_center.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits/rolls back and then always closes.

        ``sqlite3.Connection`` used as a context manager only manages the
        transaction; it never closes the connection. Long-lived processes that
        opened a fresh connection per query leaked one set of file descriptors
        (db + ``-wal`` + ``-shm``) each call, eventually exhausting the
        process fd limit and failing with "unable to open database file".
        """
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._session() as conn:
            migrated_snapshots = False
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS news_sources (
                  source_id TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL,
                  url TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1,
                  consecutive_failures INTEGER NOT NULL DEFAULT 0,
                  last_success_at TEXT, last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS news_articles (
                  article_id TEXT PRIMARY KEY, canonical_url TEXT NOT NULL UNIQUE,
                  title TEXT NOT NULL, summary TEXT NOT NULL, source_id TEXT NOT NULL,
                  sector TEXT NOT NULL, published_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
                  title_fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS news_matches (
                  article_id TEXT NOT NULL, market TEXT NOT NULL, code TEXT NOT NULL,
                  match_level TEXT NOT NULL, confidence REAL NOT NULL,
                  PRIMARY KEY(article_id, market, code)
                );
                CREATE TABLE IF NOT EXISTS stock_profiles (
                  market TEXT NOT NULL, code TEXT NOT NULL, payload_json TEXT NOT NULL,
                  profile_version TEXT NOT NULL, expires_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  PRIMARY KEY(market, code, profile_version)
                );
                CREATE TABLE IF NOT EXISTS news_analyses (
                  article_id TEXT NOT NULL, market TEXT NOT NULL, code TEXT NOT NULL,
                  analysis_date TEXT NOT NULL, prompt_version TEXT NOT NULL,
                  payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
                  PRIMARY KEY(article_id, market, code, analysis_date, prompt_version)
                );
                CREATE TABLE IF NOT EXISTS news_ai_digests (
                  date_key TEXT NOT NULL, language TEXT NOT NULL,
                  payload_json TEXT NOT NULL, model TEXT NOT NULL,
                  generated_at TEXT NOT NULL,
                  PRIMARY KEY(date_key, language)
                );
                CREATE TABLE IF NOT EXISTS opportunity_snapshots (
                  market TEXT NOT NULL, code TEXT NOT NULL, snapshot_date TEXT NOT NULL,
                  score_version TEXT NOT NULL, strategy_version TEXT NOT NULL,
                  payload_json TEXT NOT NULL, trigger TEXT NOT NULL,
                  sample_source TEXT NOT NULL DEFAULT 'live',
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  PRIMARY KEY(market, code, snapshot_date, score_version, strategy_version, sample_source)
                );
                CREATE TABLE IF NOT EXISTS refresh_jobs (
                  job_id TEXT PRIMARY KEY, status TEXT NOT NULL, markets_json TEXT NOT NULL,
                  market_dates_json TEXT NOT NULL, trigger TEXT NOT NULL,
                  completed INTEGER NOT NULL, total INTEGER NOT NULL,
                  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                  updated_at TEXT NOT NULL, error TEXT
                );
                CREATE TABLE IF NOT EXISTS opportunity_outcomes (
                  market TEXT NOT NULL, code TEXT NOT NULL, snapshot_date TEXT NOT NULL,
                  horizon_days INTEGER NOT NULL, rank INTEGER NOT NULL, is_top3 INTEGER NOT NULL,
                  status TEXT NOT NULL, entry_date TEXT, entry_price REAL,
                  exit_date TEXT, exit_price REAL, stock_return REAL,
                  benchmark_return REAL, excess_return REAL, error TEXT,
                  calibration_version TEXT NOT NULL, created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL, sample_source TEXT NOT NULL DEFAULT 'live',
                  PRIMARY KEY (market, code, snapshot_date, horizon_days, calibration_version, sample_source)
                );
                """
            )
            snapshot_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(opportunity_snapshots)").fetchall()
            }
            snapshot_pk = [
                row["name"]
                for row in sorted(
                    conn.execute("PRAGMA table_info(opportunity_snapshots)").fetchall(),
                    key=lambda row: row["pk"],
                )
                if row["pk"]
            ]
            if "sample_source" not in snapshot_columns or "sample_source" not in snapshot_pk:
                conn.executescript(
                    """
                    ALTER TABLE opportunity_snapshots RENAME TO opportunity_snapshots_legacy;
                    CREATE TABLE opportunity_snapshots (
                      market TEXT NOT NULL, code TEXT NOT NULL, snapshot_date TEXT NOT NULL,
                      score_version TEXT NOT NULL, strategy_version TEXT NOT NULL,
                      payload_json TEXT NOT NULL, trigger TEXT NOT NULL,
                      sample_source TEXT NOT NULL DEFAULT 'live',
                      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                      PRIMARY KEY(market, code, snapshot_date, score_version, strategy_version, sample_source)
                    );
                    INSERT INTO opportunity_snapshots
                      (market, code, snapshot_date, score_version, strategy_version, payload_json,
                       trigger, sample_source, created_at, updated_at)
                    SELECT market, code, snapshot_date, score_version, strategy_version, payload_json,
                           trigger,
                           CASE WHEN trigger = 'fixed-universe-backfill'
                                THEN 'fixed_universe_backfill' ELSE 'live' END,
                           created_at, updated_at
                    FROM opportunity_snapshots_legacy;
                    DROP TABLE opportunity_snapshots_legacy;
                    """
                )
                migrated_snapshots = True
            refresh_job_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(refresh_jobs)").fetchall()
            }
            for column in ("started_at", "finished_at"):
                if column not in refresh_job_columns:
                    conn.execute(f"ALTER TABLE refresh_jobs ADD COLUMN {column} TEXT")
            outcome_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(opportunity_outcomes)").fetchall()
            }
            if "sample_source" not in outcome_columns:
                conn.execute("ALTER TABLE opportunity_outcomes ADD COLUMN sample_source TEXT NOT NULL DEFAULT 'live'")
            outcome_pk = [
                row["name"]
                for row in sorted(
                    conn.execute("PRAGMA table_info(opportunity_outcomes)").fetchall(),
                    key=lambda row: row["pk"],
                )
                if row["pk"]
            ]
            if "sample_source" not in outcome_pk:
                conn.executescript(
                    """
                    ALTER TABLE opportunity_outcomes RENAME TO opportunity_outcomes_legacy;
                    CREATE TABLE opportunity_outcomes (
                      market TEXT NOT NULL, code TEXT NOT NULL, snapshot_date TEXT NOT NULL,
                      horizon_days INTEGER NOT NULL, rank INTEGER NOT NULL, is_top3 INTEGER NOT NULL,
                      status TEXT NOT NULL, entry_date TEXT, entry_price REAL,
                      exit_date TEXT, exit_price REAL, stock_return REAL,
                      benchmark_return REAL, excess_return REAL, error TEXT,
                      calibration_version TEXT NOT NULL, created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL, sample_source TEXT NOT NULL DEFAULT 'live',
                      PRIMARY KEY (market, code, snapshot_date, horizon_days, calibration_version, sample_source)
                    );
                    INSERT INTO opportunity_outcomes
                    SELECT * FROM opportunity_outcomes_legacy;
                    DROP TABLE opportunity_outcomes_legacy;
                    """
                )
            if migrated_snapshots:
                self._rebuild_snapshot_score_changes(conn)

    @staticmethod
    def _rebuild_snapshot_score_changes(conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT rowid, market, code, sample_source, snapshot_date, payload_json
            FROM opportunity_snapshots
            ORDER BY market, code, sample_source, snapshot_date, updated_at, rowid
            """
        ).fetchall()
        previous_scores: dict[tuple[str, str, str], float | None] = {}
        for row in rows:
            payload = _json_loads(row["payload_json"])
            item = OpportunityItem.model_validate_json(payload["item_json"])
            key = (row["market"], row["code"], row["sample_source"])
            previous_score = previous_scores.get(key)
            score_change = None
            if item.score is not None and previous_score is not None:
                score_change = item.score - previous_score
            payload["item_json"] = item.model_copy(update={"score_change": score_change}).model_dump_json()
            conn.execute(
                "UPDATE opportunity_snapshots SET payload_json = ? WHERE rowid = ?",
                (json.dumps(payload, ensure_ascii=False), row["rowid"]),
            )
            previous_scores[key] = item.score

    def upsert_articles(
        self,
        articles: list[NewsArticle],
        *,
        source: Mapping[str, Any] | None = None,
        fetched_at: str | None = None,
        error: str | None = None,
    ) -> list[NewsArticle]:
        now = fetched_at or utc_now()
        saved: list[NewsArticle] = []
        with self._session() as conn:
            if source is not None:
                source_row = _source_payload(source)
                existing = conn.execute(
                    "SELECT source_id FROM news_sources WHERE url = ?",
                    (source_row["url"],),
                ).fetchone()
                if existing is not None and existing["source_id"] != source_row["source_id"]:
                    old_source_id = existing["source_id"]
                    conn.execute(
                        "UPDATE news_articles SET source_id = ? WHERE source_id = ?",
                        (source_row["source_id"], old_source_id),
                    )
                    target_exists = conn.execute(
                        "SELECT 1 FROM news_sources WHERE source_id = ?",
                        (source_row["source_id"],),
                    ).fetchone()
                    if target_exists:
                        conn.execute("DELETE FROM news_sources WHERE source_id = ?", (old_source_id,))
                    else:
                        conn.execute(
                            "UPDATE news_sources SET source_id = ? WHERE source_id = ?",
                            (source_row["source_id"], old_source_id),
                        )
                if error is None:
                    conn.execute(
                        """
                        INSERT INTO news_sources
                            (source_id, name, sector, url, active, consecutive_failures, last_success_at, last_error)
                        VALUES (?, ?, ?, ?, 1, 0, ?, NULL)
                        ON CONFLICT(source_id) DO UPDATE SET
                            name = excluded.name,
                            sector = excluded.sector,
                            url = excluded.url,
                            active = 1,
                            consecutive_failures = 0,
                            last_success_at = excluded.last_success_at,
                            last_error = NULL
                        """,
                        (
                            source_row["source_id"],
                            source_row["name"],
                            source_row["sector"],
                            source_row["url"],
                            now,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO news_sources
                            (source_id, name, sector, url, active, consecutive_failures, last_success_at, last_error)
                        VALUES (?, ?, ?, ?, 1, 1, NULL, ?)
                        ON CONFLICT(source_id) DO UPDATE SET
                            name = excluded.name,
                            sector = excluded.sector,
                            url = excluded.url,
                            active = 1,
                            consecutive_failures = news_sources.consecutive_failures + 1,
                            last_error = excluded.last_error
                        """,
                        (
                            source_row["source_id"],
                            source_row["name"],
                            source_row["sector"],
                            source_row["url"],
                            error,
                        ),
                    )

            if error is not None:
                return saved

            for article in articles:
                source_row = _source_payload(source, article)
                conn.execute(
                    """
                    INSERT INTO news_sources
                        (source_id, name, sector, url, active, consecutive_failures, last_success_at, last_error)
                    VALUES (?, ?, ?, ?, 1, 0, ?, NULL)
                    ON CONFLICT(source_id) DO UPDATE SET
                        name = excluded.name,
                        sector = excluded.sector,
                        url = excluded.url,
                        active = 1,
                        consecutive_failures = 0,
                        last_success_at = excluded.last_success_at,
                        last_error = NULL
                    """,
                    (
                        source_row["source_id"],
                        source_row["name"],
                        source_row["sector"],
                        source_row["url"],
                        now,
                    ),
                )
                canonical_url = canonicalize_url(article.url)
                existing = conn.execute(
                    """
                    SELECT article_id
                    FROM news_articles
                    WHERE canonical_url = ?
                    """,
                    (canonical_url,),
                ).fetchone()
                if existing is None:
                    existing = conn.execute(
                        "SELECT article_id FROM news_articles WHERE article_id = ?",
                        (article.article_id,),
                    ).fetchone()
                if existing is None:
                    persisted_article_id = article.article_id
                    conn.execute(
                        """
                        INSERT INTO news_articles
                            (article_id, canonical_url, title, summary, source_id, sector, published_at, fetched_at, title_fingerprint)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            article.article_id,
                            canonical_url,
                            article.title,
                            article.summary,
                            source_row["source_id"],
                            source_row["sector"],
                            article.published_at,
                            now,
                            title_fingerprint(article.title),
                        ),
                    )
                else:
                    persisted_article_id = existing["article_id"]
                    conn.execute(
                        """
                        UPDATE news_articles
                        SET canonical_url = ?, title = ?, summary = ?, source_id = ?, sector = ?,
                            published_at = ?, fetched_at = ?, title_fingerprint = ?
                        WHERE article_id = ?
                        """,
                        (
                            canonical_url,
                            article.title,
                            article.summary,
                            source_row["source_id"],
                            source_row["sector"],
                            article.published_at,
                            now,
                            title_fingerprint(article.title),
                            existing["article_id"],
                        ),
                    )
                saved.append(
                    article.model_copy(
                        update={"article_id": persisted_article_id, "url": canonical_url}
                    )
                )
        return saved

    def find_recent_articles(self, *, since: str | None = None, limit: int = 200) -> list[NewsArticle]:
        sql = """
            SELECT
                news_articles.article_id,
                news_sources.name AS source,
                news_articles.title,
                news_articles.canonical_url AS url,
                news_articles.published_at,
                news_articles.summary
            FROM news_articles
            JOIN news_sources ON news_sources.source_id = news_articles.source_id
        """
        params: list[Any] = []
        if since is not None:
            sql += " WHERE news_articles.published_at >= ?"
            params.append(since)
        sql += " ORDER BY news_articles.published_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._session() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [NewsArticle.model_validate(dict(row)) for row in rows]

    def list_news_center_articles(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._session() as conn:
            articles = conn.execute(
                """
                SELECT a.article_id, s.name AS source, a.title,
                       a.canonical_url AS url, a.published_at, a.summary, a.sector
                FROM news_articles a
                JOIN news_sources s ON s.source_id = a.source_id
                ORDER BY a.published_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for article in articles:
                matches = conn.execute(
                    """
                    SELECT m.market, m.code, m.match_level, m.confidence,
                           na.payload_json
                    FROM news_matches m
                    LEFT JOIN news_analyses na ON na.rowid = (
                        SELECT latest.rowid FROM news_analyses latest
                        WHERE latest.article_id = m.article_id
                          AND latest.market = m.market AND latest.code = m.code
                        ORDER BY latest.analysis_date DESC, latest.created_at DESC
                        LIMIT 1
                    )
                    WHERE m.article_id = ?
                    ORDER BY m.confidence DESC
                    """,
                    (article["article_id"],),
                ).fetchall()
                match_rows = []
                for match in matches:
                    analysis = _json_loads(match["payload_json"]) if match["payload_json"] else {}
                    match_rows.append({
                        "market": match["market"], "code": match["code"],
                        "match_level": match["match_level"], "confidence": match["confidence"],
                        "direction": analysis.get("direction"), "strength": analysis.get("strength"),
                    })
                result.append({**dict(article), "matches": match_rows})
        return result

    def save_matches(self, article_id: str, matches: list[Mapping[str, Any]]) -> None:
        with self._session() as conn:
            for match in matches:
                conn.execute(
                    """
                    INSERT INTO news_matches (article_id, market, code, match_level, confidence)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(article_id, market, code) DO UPDATE SET
                        match_level = excluded.match_level,
                        confidence = excluded.confidence
                    """,
                    (
                        article_id,
                        str(match["market"]),
                        str(match["code"]),
                        str(match["match_level"]),
                        float(match["confidence"]),
                    ),
                )

    def get_news_analysis(
        self,
        article_id: str,
        market: str,
        code: str,
        analysis_date: str,
        prompt_version: str,
    ) -> NewsImpact | None:
        with self._session() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM news_analyses
                WHERE article_id = ? AND market = ? AND code = ? AND analysis_date = ? AND prompt_version = ?
                """,
                (article_id, market, code, analysis_date, prompt_version),
            ).fetchone()
        if row is None:
            return None
        return NewsImpact.model_validate_json(row["payload_json"])

    def save_news_analysis(self, impact: NewsImpact, analysis_date: str, prompt_version: str) -> NewsImpact:
        now = utc_now()
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO news_analyses
                    (article_id, market, code, analysis_date, prompt_version, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id, market, code, analysis_date, prompt_version) DO UPDATE SET
                    payload_json = excluded.payload_json
                """,
                (
                    impact.article_id,
                    impact.market,
                    impact.code,
                    analysis_date,
                    prompt_version,
                    impact.model_dump_json(),
                    now,
                ),
            )
        return impact

    def get_news_ai_digest(self, date_key: str, language: str) -> dict | None:
        """Cached AI daily digest payload, or None when not yet generated."""
        with self._session() as conn:
            row = conn.execute(
                "SELECT payload_json, model, generated_at FROM news_ai_digests"
                " WHERE date_key = ? AND language = ?",
                (date_key, language),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        payload["model"] = row["model"]
        payload["generated_at"] = row["generated_at"]
        return payload

    def save_news_ai_digest(
        self, date_key: str, language: str, payload: dict, model: str,
    ) -> None:
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO news_ai_digests (date_key, language, payload_json, model, generated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(date_key, language) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    model = excluded.model,
                    generated_at = excluded.generated_at
                """,
                (date_key, language, json.dumps(payload, ensure_ascii=False), model, utc_now()),
            )

    def create_job(
        self,
        *,
        job_id: str,
        markets: list[str],
        market_dates: dict[str, str],
        trigger: str,
        total: int,
        status: str = "queued",
        completed: int = 0,
        error: str | None = None,
    ) -> RefreshJob:
        with self._session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = self._active_job_row(conn)
            if active is not None:
                return self._job_from_row(active)

            now = utc_now()
            started_at = now if status == "running" else None
            finished_at = now if status in {"completed", "failed"} else None
            conn.execute(
                """
                INSERT INTO refresh_jobs
                    (job_id, status, markets_json, market_dates_json, trigger, completed, total,
                     created_at, started_at, finished_at, updated_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    status,
                    json.dumps(markets),
                    json.dumps(market_dates),
                    trigger,
                    completed,
                    total,
                    now,
                    started_at,
                    finished_at,
                    now,
                    error,
                ),
            )
            row = conn.execute("SELECT * FROM refresh_jobs WHERE job_id = ?", (job_id,)).fetchone()
        assert row is not None
        return self._job_from_row(row)

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        completed: int | None = None,
        total: int | None = None,
        error: str | None = None,
        market_dates: dict[str, str] | None = None,
    ) -> RefreshJob:
        now = utc_now()
        market_dates_json = json.dumps(market_dates) if market_dates is not None else None
        with self._session() as conn:
            conn.execute(
                """
                UPDATE refresh_jobs
                SET status = ?,
                    market_dates_json = COALESCE(?, market_dates_json),
                    completed = COALESCE(?, completed),
                    total = COALESCE(?, total),
                    started_at = CASE
                        WHEN status = 'queued' AND ? = 'running' AND started_at IS NULL THEN ?
                        ELSE started_at
                    END,
                    finished_at = CASE
                        WHEN status NOT IN ('completed', 'failed')
                             AND ? IN ('completed', 'failed')
                             AND finished_at IS NULL THEN ?
                        ELSE finished_at
                    END,
                    updated_at = ?,
                    error = ?
                WHERE job_id = ?
                  AND status NOT IN ('completed', 'failed')
                  AND (
                      (status = 'queued' AND ? IN ('queued', 'running', 'completed', 'failed'))
                      OR (status = 'running' AND ? IN ('running', 'completed', 'failed'))
                  )
                """,
                (
                    status,
                    market_dates_json,
                    completed,
                    total,
                    status,
                    now,
                    status,
                    now,
                    now,
                    error,
                    job_id,
                    status,
                    status,
                ),
            )
            updated = conn.execute("SELECT * FROM refresh_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if updated is None:
                raise ValueError("job not found")
        return self._job_from_row(updated)

    def get_active_job(self) -> RefreshJob | None:
        with self._session() as conn:
            row = self._active_job_row(conn)
        if row is None:
            return None
        return self._job_from_row(row)

    def get_job(self, job_id: str) -> RefreshJob | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM refresh_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._job_from_row(row) if row is not None else None

    def get_last_refresh_error(self) -> str | None:
        with self._session() as conn:
            row = conn.execute(
                """
                SELECT error FROM refresh_jobs
                WHERE error IS NOT NULL AND error != ''
                ORDER BY updated_at DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
        return str(row["error"]) if row is not None else None

    def upsert_snapshot(
        self,
        item: OpportunityItem | OpportunityDetail,
        *,
        trigger: str,
        detail: Mapping[str, Any] | None = None,
    ) -> OpportunityItem:
        base_item = OpportunityItem.model_validate(
            item.model_dump(include=set(OpportunityItem.model_fields))
        )
        is_backfill = trigger == "fixed-universe-backfill"
        sample_source = "fixed_universe_backfill" if is_backfill else "live"
        now = utc_now()
        with self._session() as conn:
            previous_row = conn.execute(
                """
                SELECT payload_json
                FROM opportunity_snapshots
                WHERE market = ? AND code = ? AND snapshot_date < ?
                  AND sample_source = ?
                ORDER BY snapshot_date DESC, updated_at DESC, rowid DESC
                LIMIT 1
                """,
                (
                    base_item.market,
                    base_item.code,
                    base_item.snapshot_date,
                    sample_source,
                ),
            ).fetchone()
            previous_score = None
            if previous_row is not None:
                previous_item = self._snapshot_item_from_payload(previous_row["payload_json"])
                previous_score = previous_item.score

            score_change = None
            if base_item.score is not None and previous_score is not None:
                score_change = base_item.score - previous_score
            stored_item = base_item.model_copy(update={"score_change": score_change})

            detail_payload: dict[str, Any] = {}
            if isinstance(item, OpportunityDetail):
                detail_payload.update(
                    {
                        "news": [news.model_dump(mode="json") for news in item.news],
                        "explanations": list(item.explanations),
                        "history_available": item.history_available,
                    }
                )
            if detail is not None:
                detail_payload.update(detail)

            payload_json = json.dumps(
                {
                    "item_json": stored_item.model_dump_json(),
                    "detail": detail_payload,
                },
                ensure_ascii=False,
            )
            existing = conn.execute(
                """
                SELECT created_at
                FROM opportunity_snapshots
                WHERE market = ? AND code = ? AND snapshot_date = ? AND score_version = ?
                  AND strategy_version = ? AND sample_source = ?
                """,
                (
                    stored_item.market,
                    stored_item.code,
                    stored_item.snapshot_date,
                    stored_item.score_version,
                    stored_item.strategy_version,
                    sample_source,
                ),
            ).fetchone()
            created_at = existing["created_at"] if existing is not None else now
            conn.execute(
                """
                INSERT INTO opportunity_snapshots
                    (market, code, snapshot_date, score_version, strategy_version, payload_json,
                     trigger, sample_source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market, code, snapshot_date, score_version, strategy_version, sample_source)
                DO UPDATE SET
                    payload_json = excluded.payload_json,
                    trigger = excluded.trigger,
                    updated_at = excluded.updated_at
                """,
                (
                    stored_item.market,
                    stored_item.code,
                    stored_item.snapshot_date,
                    stored_item.score_version,
                    stored_item.strategy_version,
                    payload_json,
                    trigger,
                    sample_source,
                    created_at,
                    now,
                ),
            )

            next_date_row = conn.execute(
                """
                SELECT MIN(snapshot_date) AS snapshot_date
                FROM opportunity_snapshots
                WHERE market = ? AND code = ? AND snapshot_date > ?
                  AND sample_source = ?
                """,
                (stored_item.market, stored_item.code, stored_item.snapshot_date, sample_source),
            ).fetchone()
            next_date = next_date_row["snapshot_date"] if next_date_row is not None else None
            if next_date is not None:
                successor_rows = conn.execute(
                    """
                    SELECT score_version, strategy_version, payload_json
                    FROM opportunity_snapshots
                    WHERE market = ? AND code = ? AND snapshot_date = ?
                      AND sample_source = ?
                    ORDER BY updated_at DESC, rowid DESC
                    """,
                    (stored_item.market, stored_item.code, next_date, sample_source),
                ).fetchall()
                for successor_row in successor_rows:
                    successor_payload = _json_loads(successor_row["payload_json"])
                    successor_item = OpportunityItem.model_validate_json(
                        successor_payload["item_json"]
                    )
                    successor_change = None
                    if successor_item.score is not None and stored_item.score is not None:
                        successor_change = successor_item.score - stored_item.score
                    successor_payload["item_json"] = successor_item.model_copy(
                        update={"score_change": successor_change}
                    ).model_dump_json()
                    conn.execute(
                        """
                        UPDATE opportunity_snapshots
                        SET payload_json = ?, updated_at = ?
                        WHERE market = ? AND code = ? AND snapshot_date = ?
                          AND score_version = ? AND strategy_version = ? AND sample_source = ?
                        """,
                        (
                            json.dumps(successor_payload, ensure_ascii=False),
                            now,
                            stored_item.market,
                            stored_item.code,
                            next_date,
                            successor_row["score_version"],
                            successor_row["strategy_version"],
                            sample_source,
                        ),
                    )
        return stored_item

    def list_latest(
        self,
        *,
        market: str | None,
        signal: str | None,
        level: str | None,
        limit: int = 200,
    ) -> list[OpportunityItem]:
        with self._session() as conn:
            rows = conn.execute(
                """
                WITH ranked AS (
                    SELECT
                        payload_json,
                        snapshot_date,
                        updated_at,
                        rowid AS snapshot_rowid,
                        ROW_NUMBER() OVER (
                            PARTITION BY market, code
                            ORDER BY snapshot_date DESC, updated_at DESC, rowid DESC
                        ) AS snapshot_rank
                    FROM opportunity_snapshots
                    WHERE sample_source = 'live'
                )
                SELECT payload_json
                FROM ranked
                WHERE snapshot_rank = 1
                ORDER BY snapshot_date DESC, updated_at DESC, snapshot_rowid DESC
                """,
            ).fetchall()
        items = [self._snapshot_item_from_payload(row["payload_json"]) for row in rows]
        if market is not None:
            items = [item for item in items if item.market == market]
        if signal is not None:
            items = [item for item in items if item.latest_action == signal]
        if level is not None:
            items = [item for item in items if item.level == level]
        return items[: max(1, min(limit, 500))]

    def get_detail(self, market: str, code: str, snapshot_date: str | None = None) -> OpportunityDetail | None:
        sql = """
            SELECT payload_json
            FROM opportunity_snapshots
            WHERE market = ? AND code = ? AND sample_source = 'live'
        """
        params: list[Any] = [market, code]
        if snapshot_date is not None:
            sql += " AND snapshot_date = ?"
            params.append(snapshot_date)
        sql += " ORDER BY snapshot_date DESC, updated_at DESC, rowid DESC LIMIT 1"
        with self._session() as conn:
            row = conn.execute(sql, params).fetchone()
        if row is None:
            return None

        payload = _json_loads(row["payload_json"])
        item = OpportunityItem.model_validate_json(payload["item_json"])
        detail_payload = dict(payload.get("detail", {}))
        persisted_news = self._news_for_snapshot(item.market, item.code, item.snapshot_date)
        if "news" not in detail_payload:
            detail_payload["news"] = [news.model_dump(mode="json") for news in persisted_news]
        detail_payload["history_available"] = detail_payload.get("history_available", False) or len(
            self.get_history(market, code, limit=2)
        ) > 1
        detail_payload.setdefault("explanations", [])
        return OpportunityDetail.model_validate({**item.model_dump(mode="json"), **detail_payload})

    def get_history(self, market: str, code: str, *, limit: int = 30) -> list[OpportunityItem]:
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM opportunity_snapshots
                WHERE market = ? AND code = ?
                  AND sample_source = 'live'
                ORDER BY snapshot_date DESC, updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (market, code, max(1, min(limit, 500))),
            ).fetchall()
        return [self._snapshot_item_from_payload(row["payload_json"]) for row in rows]

    def list_snapshot_items(self) -> list[OpportunityItem]:
        with self._session() as conn:
            rows = conn.execute(
                """
                WITH ranked AS (
                    SELECT payload_json, market, code, snapshot_date,
                           ROW_NUMBER() OVER (
                               PARTITION BY market, code, snapshot_date
                               ORDER BY updated_at DESC, rowid DESC
                           ) AS version_rank
                    FROM opportunity_snapshots
                )
                SELECT payload_json FROM ranked
                WHERE version_rank = 1
                ORDER BY snapshot_date, market, code
                """
            ).fetchall()
        return [self._snapshot_item_from_payload(row["payload_json"]) for row in rows]

    def upsert_outcome(self, outcome: OpportunityOutcome) -> OpportunityOutcome:
        now = utc_now()
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO opportunity_outcomes
                    (market, code, snapshot_date, horizon_days, rank, is_top3, status,
                     entry_date, entry_price, exit_date, exit_price, stock_return,
                     benchmark_return, excess_return, error, calibration_version,
                     created_at, updated_at, sample_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market, code, snapshot_date, horizon_days, calibration_version, sample_source)
                DO UPDATE SET
                    rank = excluded.rank,
                    is_top3 = excluded.is_top3,
                    status = excluded.status,
                    entry_date = excluded.entry_date,
                    entry_price = excluded.entry_price,
                    exit_date = excluded.exit_date,
                    exit_price = excluded.exit_price,
                    stock_return = excluded.stock_return,
                    benchmark_return = excluded.benchmark_return,
                    excess_return = excluded.excess_return,
                    error = excluded.error,
                    sample_source = excluded.sample_source,
                    updated_at = excluded.updated_at
                WHERE excluded.status = 'completed' OR opportunity_outcomes.status != 'completed'
                """,
                (
                    outcome.market, outcome.code, outcome.snapshot_date, outcome.horizon_days,
                    outcome.rank, int(outcome.is_top3), outcome.status, outcome.entry_date,
                    outcome.entry_price, outcome.exit_date, outcome.exit_price,
                    outcome.stock_return, outcome.benchmark_return, outcome.excess_return,
                    outcome.error, outcome.calibration_version, now, now, outcome.sample_source,
                ),
            )
            row = conn.execute(
                """SELECT * FROM opportunity_outcomes
                   WHERE market = ? AND code = ? AND snapshot_date = ?
                     AND horizon_days = ? AND calibration_version = ? AND sample_source = ?""",
                (
                    outcome.market, outcome.code, outcome.snapshot_date, outcome.horizon_days,
                    outcome.calibration_version, outcome.sample_source,
                ),
            ).fetchone()
        assert row is not None
        return self._outcome_from_row(row)

    def list_outcomes(self) -> list[OpportunityOutcome]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM opportunity_outcomes ORDER BY snapshot_date, market, code, horizon_days"
            ).fetchall()
        return [self._outcome_from_row(row) for row in rows]

    def get_calibration_summary(self, scope: str = "top3") -> OpportunityCalibrationSummary:
        if scope not in {"top3", "all"}:
            raise ValueError("scope must be top3 or all")
        where = "WHERE is_top3 = 1" if scope == "top3" else ""
        with self._session() as conn:
            rows = conn.execute(
                f"SELECT * FROM opportunity_outcomes {where} ORDER BY horizon_days"  # noqa: S608
            ).fetchall()
        outcomes = [self._outcome_from_row(row) for row in rows]
        periods: list[CalibrationPeriodSummary] = []
        for horizon in (5, 20, 60):
            matching = [item for item in outcomes if item.horizon_days == horizon]
            completed = [item for item in matching if item.status == "completed"]
            stock_returns = [item.stock_return for item in completed if item.stock_return is not None]
            excess_returns = [item.excess_return for item in completed if item.excess_return is not None]
            periods.append(CalibrationPeriodSummary(
                horizon_days=horizon,
                completed_samples=len(completed),
                pending_samples=sum(item.status == "pending" for item in matching),
                missing_samples=sum(item.status == "missing" for item in matching),
                win_rate=(sum(value > 0 for value in stock_returns) / len(stock_returns)) if stock_returns else None,
                outperformance_rate=(sum(value > 0 for value in excess_returns) / len(excess_returns)) if excess_returns else None,
                average_return=(sum(stock_returns) / len(stock_returns)) if stock_returns else None,
                average_excess_return=(sum(excess_returns) / len(excess_returns)) if excess_returns else None,
                max_loss=min(0.0, min(stock_returns)) if stock_returns else None,
            ))
        calculated_at = max((item.updated_at or "" for item in outcomes), default="") or None
        has_backfill = any(item.sample_source == "fixed_universe_backfill" for item in outcomes)
        note = "包含固定当前自选股历史回放，存在幸存者偏差。" if has_backfill else ""
        return OpportunityCalibrationSummary(
            scope=scope, periods=periods, calculated_at=calculated_at,
            contains_fixed_universe_backfill=has_backfill, methodology_note=note,
        )

    @staticmethod
    def _outcome_from_row(row: sqlite3.Row) -> OpportunityOutcome:
        return OpportunityOutcome(
            market=row["market"], code=row["code"], snapshot_date=row["snapshot_date"],
            horizon_days=row["horizon_days"], rank=row["rank"], is_top3=bool(row["is_top3"]),
            status=row["status"], entry_date=row["entry_date"], entry_price=row["entry_price"],
            exit_date=row["exit_date"], exit_price=row["exit_price"], stock_return=row["stock_return"],
            benchmark_return=row["benchmark_return"], excess_return=row["excess_return"],
            error=row["error"], calibration_version=row["calibration_version"],
            sample_source=row["sample_source"],
            updated_at=row["updated_at"],
        )

    def has_market_refresh(self, market: str, market_date: str) -> bool:
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT market_dates_json
                FROM refresh_jobs
                WHERE status = 'completed'
                ORDER BY updated_at DESC
                """
            ).fetchall()
        for row in rows:
            dates = _json_loads(row["market_dates_json"])
            if dates.get(market) == market_date:
                return True
        return False

    def _job_from_row(self, row: sqlite3.Row) -> RefreshJob:
        return RefreshJob(
            job_id=row["job_id"],
            status=row["status"],
            markets=list(_json_loads(row["markets_json"])),
            trigger=row["trigger"],
            completed=row["completed"],
            total=row["total"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            updated_at=row["updated_at"],
            error=row["error"],
        )

    def _active_job_row(self, conn: sqlite3.Connection) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT *
            FROM refresh_jobs
            WHERE status IN ('running', 'queued')
            ORDER BY
                CASE status WHEN 'running' THEN 0 ELSE 1 END,
                created_at ASC,
                job_id ASC
            LIMIT 1
            """
        ).fetchone()

    def _news_for_snapshot(self, market: str, code: str, snapshot_date: str) -> list[NewsImpact]:
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM news_analyses
                WHERE market = ? AND code = ? AND analysis_date = ?
                ORDER BY created_at DESC
                """,
                (market, code, snapshot_date),
            ).fetchall()
        return [NewsImpact.model_validate_json(row["payload_json"]) for row in rows]

    def _snapshot_item_from_payload(self, payload_json: str) -> OpportunityItem:
        payload = _json_loads(payload_json)
        return OpportunityItem.model_validate_json(payload["item_json"])
