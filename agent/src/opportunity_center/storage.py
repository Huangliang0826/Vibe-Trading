"""SQLite persistence for opportunity-center data."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.config.paths import get_runtime_root
from src.opportunity_center.models import NewsArticle, NewsImpact, OpportunityDetail, OpportunityItem, RefreshJob


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
    return slug or "source"


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

    def _init_db(self) -> None:
        with self._connect() as conn:
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
                CREATE TABLE IF NOT EXISTS opportunity_snapshots (
                  market TEXT NOT NULL, code TEXT NOT NULL, snapshot_date TEXT NOT NULL,
                  score_version TEXT NOT NULL, strategy_version TEXT NOT NULL,
                  payload_json TEXT NOT NULL, trigger TEXT NOT NULL,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  PRIMARY KEY(market, code, snapshot_date, score_version, strategy_version)
                );
                CREATE TABLE IF NOT EXISTS refresh_jobs (
                  job_id TEXT PRIMARY KEY, status TEXT NOT NULL, markets_json TEXT NOT NULL,
                  market_dates_json TEXT NOT NULL, trigger TEXT NOT NULL,
                  completed INTEGER NOT NULL, total INTEGER NOT NULL,
                  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                  updated_at TEXT NOT NULL, error TEXT
                );
                """
            )
            refresh_job_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(refresh_jobs)").fetchall()
            }
            for column in ("started_at", "finished_at"):
                if column not in refresh_job_columns:
                    conn.execute(f"ALTER TABLE refresh_jobs ADD COLUMN {column} TEXT")

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
        with self._connect() as conn:
            if source is not None:
                source_row = _source_payload(source)
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
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [NewsArticle.model_validate(dict(row)) for row in rows]

    def save_matches(self, article_id: str, matches: list[Mapping[str, Any]]) -> None:
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM refresh_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("job not found")
            started_at = row["started_at"]
            if row["status"] == "queued" and status == "running" and started_at is None:
                started_at = now
            finished_at = row["finished_at"]
            if (
                row["status"] not in {"completed", "failed"}
                and status in {"completed", "failed"}
                and finished_at is None
            ):
                finished_at = now
            conn.execute(
                """
                UPDATE refresh_jobs
                SET status = ?, market_dates_json = ?, completed = ?, total = ?,
                    started_at = ?, finished_at = ?, updated_at = ?, error = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    json.dumps(market_dates) if market_dates is not None else row["market_dates_json"],
                    row["completed"] if completed is None else completed,
                    row["total"] if total is None else total,
                    started_at,
                    finished_at,
                    now,
                    error,
                    job_id,
                ),
            )
            updated = conn.execute("SELECT * FROM refresh_jobs WHERE job_id = ?", (job_id,)).fetchone()
        assert updated is not None
        return self._job_from_row(updated)

    def get_active_job(self) -> RefreshJob | None:
        with self._connect() as conn:
            row = self._active_job_row(conn)
        if row is None:
            return None
        return self._job_from_row(row)

    def upsert_snapshot(
        self,
        item: OpportunityItem | OpportunityDetail,
        *,
        trigger: str,
        detail: Mapping[str, Any] | None = None,
    ) -> OpportunityItem:
        base_item = OpportunityItem.model_validate(item.model_dump())
        now = utc_now()
        with self._connect() as conn:
            previous_row = conn.execute(
                """
                SELECT payload_json
                FROM opportunity_snapshots
                WHERE market = ? AND code = ?
                  AND NOT (
                    snapshot_date = ? AND score_version = ? AND strategy_version = ?
                  )
                ORDER BY snapshot_date DESC, updated_at DESC
                LIMIT 1
                """,
                (
                    base_item.market,
                    base_item.code,
                    base_item.snapshot_date,
                    base_item.score_version,
                    base_item.strategy_version,
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
                WHERE market = ? AND code = ? AND snapshot_date = ? AND score_version = ? AND strategy_version = ?
                """,
                (
                    stored_item.market,
                    stored_item.code,
                    stored_item.snapshot_date,
                    stored_item.score_version,
                    stored_item.strategy_version,
                ),
            ).fetchone()
            created_at = existing["created_at"] if existing is not None else now
            conn.execute(
                """
                INSERT INTO opportunity_snapshots
                    (market, code, snapshot_date, score_version, strategy_version, payload_json, trigger, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market, code, snapshot_date, score_version, strategy_version) DO UPDATE SET
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
                    created_at,
                    now,
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
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM opportunity_snapshots AS current
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM opportunity_snapshots AS newer
                    WHERE newer.market = current.market
                      AND newer.code = current.code
                      AND (
                        newer.snapshot_date > current.snapshot_date
                        OR (
                            newer.snapshot_date = current.snapshot_date
                            AND newer.updated_at > current.updated_at
                        )
                      )
                )
                ORDER BY snapshot_date DESC, updated_at DESC
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
            WHERE market = ? AND code = ?
        """
        params: list[Any] = [market, code]
        if snapshot_date is not None:
            sql += " AND snapshot_date = ?"
            params.append(snapshot_date)
        sql += " ORDER BY snapshot_date DESC, updated_at DESC LIMIT 1"
        with self._connect() as conn:
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
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM opportunity_snapshots
                WHERE market = ? AND code = ?
                ORDER BY snapshot_date DESC, updated_at DESC
                LIMIT ?
                """,
                (market, code, max(1, min(limit, 500))),
            ).fetchall()
        return [self._snapshot_item_from_payload(row["payload_json"]) for row in rows]

    def has_market_refresh(self, market: str, market_date: str) -> bool:
        with self._connect() as conn:
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
        with self._connect() as conn:
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
