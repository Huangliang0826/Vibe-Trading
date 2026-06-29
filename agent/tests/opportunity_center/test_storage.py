from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.opportunity_center.models import (
    SCORE_VERSION,
    STRATEGY_VERSION,
    DimensionScores,
    NewsArticle,
    NewsImpact,
    OpportunityItem,
)
from src.opportunity_center.storage import OpportunityStore


class CoordinatedJobConnection(sqlite3.Connection):
    read_barrier: threading.Barrier | None = None

    def execute(self, sql, parameters=(), /):
        normalized_sql = " ".join(sql.split())
        is_job_update = normalized_sql.startswith("UPDATE refresh_jobs")
        if is_job_update:
            self._job_updated = True
        cursor = super().execute(sql, parameters)
        if (
            normalized_sql.startswith("SELECT * FROM refresh_jobs WHERE job_id")
            and not getattr(self, "_job_updated", False)
            and self.read_barrier is not None
        ):
            self.read_barrier.wait(timeout=5)
        return cursor


def sample_item(
    *,
    market: str = "hk",
    code: str = "0700",
    company_name: str = "腾讯控股",
    snapshot_date: str = "2026-06-29",
    score: float | None = 78,
    level: str = "值得观察",
    latest_action: str = "hold",
    signal_date: str | None = "2026-06-28",
) -> OpportunityItem:
    return OpportunityItem(
        market=market,
        code=code,
        company_name=company_name,
        snapshot_date=snapshot_date,
        score=score,
        level=level,
        latest_action=latest_action,
        signal_date=signal_date,
        strategy_name="quality_momentum",
        strategy_label="收益质量动量",
        primary_reason="趋势改善",
        risk_reasons=["波动偏高"],
        dimensions=DimensionScores(
            strategy=80,
            trend=75,
            risk=62,
            news=55,
            valuation=48,
        ),
        data_as_of=snapshot_date,
        score_version=SCORE_VERSION,
        strategy_version=STRATEGY_VERSION,
    )


def sample_article(
    *,
    article_id: str = "a1",
    title: str = "NVIDIA launches platform",
    url: str = "https://example.com/story?utm_source=rss",
    published_at: str = "2026-06-29T08:00:00Z",
    source: str = "OpenAI",
) -> NewsArticle:
    return NewsArticle(
        article_id=article_id,
        source=source,
        title=title,
        url=url,
        published_at=published_at,
        summary="High-signal article",
    )


def sample_impact(
    *,
    article_id: str = "a1",
    market: str = "hk",
    code: str = "0700",
    direction: str = "positive",
) -> NewsImpact:
    return NewsImpact(
        article_id=article_id,
        market=market,
        code=code,
        direction=direction,
        strength=81,
        confidence=78,
        horizon="short",
        summary="需求改善",
        rationale="行业催化增强",
        match_level="direct",
    )


def sample_source(
    *,
    source_id: str = "openai",
    name: str = "OpenAI",
    sector: str = "ai",
    url: str = "https://openai.com/news/rss.xml",
) -> dict[str, str]:
    return {
        "source_id": source_id,
        "name": name,
        "sector": sector,
        "url": url,
    }


def fetch_source_row(store: OpportunityStore, source_id: str) -> sqlite3.Row:
    with store._connect() as conn:
        row = conn.execute(
            """
            SELECT source_id, consecutive_failures, last_success_at, last_error
            FROM news_sources
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()
    assert row is not None
    return row


def test_store_uses_runtime_root_db_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr("src.opportunity_center.storage.get_runtime_root", lambda: tmp_path)

    store = OpportunityStore()

    assert store.db_path == tmp_path / "opportunity_center.db"
    assert store.db_path.exists()


def test_snapshot_unique_key_is_idempotent(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    item = sample_item(score=78)

    store.upsert_snapshot(item, trigger="scheduled", detail={"reason": "first"})
    store.upsert_snapshot(
        item.model_copy(update={"score": 80}),
        trigger="manual",
        detail={"reason": "updated"},
    )

    rows = store.get_history("hk", "0700", limit=20)
    assert len(rows) == 1
    assert rows[0].score == 80


def test_backfilled_snapshot_score_change_uses_newest_strictly_earlier_date(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    store.upsert_snapshot(
        sample_item(snapshot_date="2026-06-27", score=70),
        trigger="scheduled",
    )
    store.upsert_snapshot(
        sample_item(snapshot_date="2026-06-29", score=90),
        trigger="scheduled",
    )

    backfilled = store.upsert_snapshot(
        sample_item(snapshot_date="2026-06-28", score=80),
        trigger="backfill",
    )
    backfilled_history = {
        item.snapshot_date: item.score_change for item in store.get_history("hk", "0700")
    }
    updated = store.upsert_snapshot(
        sample_item(snapshot_date="2026-06-28", score=85),
        trigger="backfill",
    )
    updated_history = {
        item.snapshot_date: item.score_change for item in store.get_history("hk", "0700")
    }

    assert backfilled.score_change == 10
    assert backfilled_history == {
        "2026-06-27": None,
        "2026-06-28": 10,
        "2026-06-29": 10,
    }
    assert updated.score_change == 15
    assert updated_history == {
        "2026-06-27": None,
        "2026-06-28": 15,
        "2026-06-29": 5,
    }


def test_news_analysis_cache_key_includes_stock_date_and_prompt(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")

    store.save_news_analysis(sample_impact(), "2026-06-29", "news-impact-v1")

    assert store.get_news_analysis("a1", "hk", "0700", "2026-06-29", "news-impact-v1") is not None
    assert store.get_news_analysis("a1", "hk", "0700", "2026-06-30", "news-impact-v1") is None
    assert store.get_news_analysis("a1", "hk", "0700", "2026-06-29", "news-impact-v2") is None


def test_canonical_url_conflict_returns_persisted_article_identity_for_analysis_cache(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    source = sample_source()
    first = store.upsert_articles([sample_article(article_id="canonical-id")], source=source)
    store.save_news_analysis(
        sample_impact(article_id=first[0].article_id),
        "2026-06-29",
        "news-impact-v1",
    )

    repeated = store.upsert_articles(
        [
            sample_article(
                article_id="changed-feed-id",
                url="https://example.com/story?utm_campaign=repeat&ref=rss",
            )
        ],
        source=source,
    )

    assert repeated[0].article_id == "canonical-id"
    cached = store.get_news_analysis(
        repeated[0].article_id,
        "hk",
        "0700",
        "2026-06-29",
        "news-impact-v1",
    )
    assert cached is not None
    assert cached.article_id == "canonical-id"


def test_upsert_articles_tracks_source_health_and_recent_articles(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    source = sample_source()

    store.upsert_articles([], source=source, error="timeout")
    failed = fetch_source_row(store, "openai")
    assert failed["consecutive_failures"] == 1
    assert failed["last_error"] == "timeout"

    saved = store.upsert_articles([sample_article()], source=source, fetched_at="2026-06-29T09:00:00Z")
    healthy = fetch_source_row(store, "openai")
    assert len(saved) == 1
    assert healthy["consecutive_failures"] == 0
    assert healthy["last_error"] is None
    assert healthy["last_success_at"] == "2026-06-29T09:00:00Z"

    recent = store.find_recent_articles(limit=10)
    assert [article.article_id for article in recent] == ["a1"]


def test_save_matches_is_idempotent_per_article_market_code(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")

    store.save_matches(
        "a1",
        [
            {"market": "hk", "code": "0700", "match_level": "direct", "confidence": 0.85},
        ],
    )
    store.save_matches(
        "a1",
        [
            {"market": "hk", "code": "0700", "match_level": "industry", "confidence": 0.55},
        ],
    )

    with store._connect() as conn:
        row = conn.execute(
            """
            SELECT match_level, confidence
            FROM news_matches
            WHERE article_id = ? AND market = ? AND code = ?
            """,
            ("a1", "hk", "0700"),
        ).fetchone()
    assert row is not None
    assert row["match_level"] == "industry"
    assert row["confidence"] == 0.55


def test_list_latest_get_detail_and_history_use_previous_snapshot_for_score_change(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    previous = sample_item(snapshot_date="2026-06-28", score=71, latest_action="wait", signal_date=None)
    latest = sample_item(snapshot_date="2026-06-29", score=83, latest_action="entry", level="优先关注")

    store.upsert_snapshot(previous, trigger="scheduled", detail={"explanations": ["前一日"]})
    store.upsert_snapshot(latest, trigger="manual", detail={"explanations": ["最新快照"]})
    store.save_news_analysis(sample_impact(), "2026-06-29", "news-impact-v1")

    listing = store.list_latest(market="hk", signal="entry", level="优先关注")
    assert len(listing) == 1
    assert listing[0].snapshot_date == "2026-06-29"
    assert listing[0].score_change == 12

    detail = store.get_detail("hk", "0700")
    assert detail is not None
    assert detail.snapshot_date == "2026-06-29"
    assert detail.news[0].article_id == "a1"
    assert detail.explanations == ["最新快照"]
    assert detail.history_available is True

    history = store.get_history("hk", "0700", limit=10)
    assert [row.snapshot_date for row in history] == ["2026-06-29", "2026-06-28"]


def test_list_latest_filters_before_limit(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")

    store.upsert_snapshot(
        sample_item(market="us", code="NVDA", company_name="NVIDIA", snapshot_date="2026-06-30"),
        trigger="scheduled",
    )
    store.upsert_snapshot(
        sample_item(snapshot_date="2026-06-29", score=83, latest_action="entry", level="优先关注"),
        trigger="scheduled",
    )

    listing = store.list_latest(market="hk", signal="entry", level="优先关注", limit=1)

    assert len(listing) == 1
    assert listing[0].market == "hk"
    assert listing[0].code == "0700"


def test_list_latest_deterministically_selects_later_same_timestamp_version(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.opportunity_center.storage.utc_now",
        lambda: "2026-06-29T12:00:00Z",
    )
    store = OpportunityStore(tmp_path / "opportunities.db")
    store.upsert_snapshot(
        sample_item(
            score=70,
            latest_action="hold",
            level="值得观察",
        ).model_copy(
            update={"score_version": "score-v1", "strategy_version": "strategy-v1"}
        ),
        trigger="scheduled",
    )
    store.upsert_snapshot(
        sample_item(
            score=83,
            latest_action="entry",
            level="优先关注",
        ).model_copy(
            update={"score_version": "score-v2", "strategy_version": "strategy-v2"}
        ),
        trigger="manual",
    )

    listing = store.list_latest(market=None, signal=None, level=None, limit=10)
    matching = store.list_latest(market="hk", signal="entry", level="优先关注", limit=1)
    superseded = store.list_latest(market="hk", signal="hold", level="值得观察", limit=1)

    assert len(listing) == 1
    assert listing[0].score_version == "score-v2"
    assert listing[0].strategy_version == "strategy-v2"
    assert listing[0].score == 83
    assert matching == listing
    assert superseded == []


@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
def test_jobs_persist_exact_transition_timestamps_and_migrate_legacy_schema(
    tmp_path,
    monkeypatch,
    terminal_status,
):
    db_path = tmp_path / "opportunities.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE refresh_jobs (
              job_id TEXT PRIMARY KEY, status TEXT NOT NULL, markets_json TEXT NOT NULL,
              market_dates_json TEXT NOT NULL, trigger TEXT NOT NULL,
              completed INTEGER NOT NULL, total INTEGER NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT
            )
            """
        )
    timestamps = iter(
        [
            "2026-06-29T08:00:00Z",
            "2026-06-29T08:05:00Z",
            "2026-06-29T08:10:00Z",
            "2026-06-29T08:15:00Z",
        ]
    )
    monkeypatch.setattr("src.opportunity_center.storage.utc_now", lambda: next(timestamps))
    store = OpportunityStore(db_path)

    created = store.create_job(
        job_id="job-1",
        markets=["hk", "us"],
        market_dates={"hk": "2026-06-29", "us": "2026-06-28"},
        trigger="scheduled",
        total=2,
    )
    assert created.status == "queued"
    assert created.created_at == "2026-06-29T08:00:00Z"
    assert created.started_at is None
    assert created.finished_at is None
    assert store.get_active_job() is not None
    assert store.has_market_refresh("hk", "2026-06-29") is False

    running = store.update_job("job-1", status="running", completed=1)
    assert running.started_at == "2026-06-29T08:05:00Z"
    assert running.started_at != running.created_at
    assert store.get_active_job() is not None

    still_running = store.update_job("job-1", status="running", completed=1)
    assert still_running.started_at == "2026-06-29T08:05:00Z"

    finished = store.update_job("job-1", status=terminal_status, completed=2)
    assert finished.started_at == "2026-06-29T08:05:00Z"
    assert finished.finished_at == "2026-06-29T08:15:00Z"
    assert finished.updated_at == "2026-06-29T08:15:00Z"
    assert store.get_active_job() is None
    assert store.has_market_refresh("hk", "2026-06-29") is (terminal_status == "completed")


@pytest.mark.parametrize("terminal_status", ["failed", "completed"])
def test_queued_job_terminal_transition_sets_finished_at_without_started_at(
    tmp_path,
    monkeypatch,
    terminal_status,
):
    timestamps = iter(["2026-06-29T09:00:00Z", "2026-06-29T09:05:00Z"])
    monkeypatch.setattr("src.opportunity_center.storage.utc_now", lambda: next(timestamps))
    store = OpportunityStore(tmp_path / "opportunities.db")
    store.create_job(
        job_id="job-1",
        markets=["hk"],
        market_dates={"hk": "2026-06-29"},
        trigger="scheduled",
        total=1,
    )

    finished = store.update_job("job-1", status=terminal_status)

    assert finished.status == terminal_status
    assert finished.started_at is None
    assert finished.finished_at == "2026-06-29T09:05:00Z"


@pytest.mark.parametrize(
    ("terminal_status", "attempted_statuses", "has_market_refresh"),
    [
        ("completed", ["running", "failed", "completed"], True),
        ("failed", ["running", "completed", "failed"], False),
    ],
)
def test_terminal_job_is_immutable(
    tmp_path,
    terminal_status,
    attempted_statuses,
    has_market_refresh,
):
    store = OpportunityStore(tmp_path / "opportunities.db")
    store.create_job(
        job_id="job-1",
        markets=["hk"],
        market_dates={"hk": "2026-06-29"},
        trigger="scheduled",
        total=1,
    )
    terminal = store.update_job(
        "job-1",
        status=terminal_status,
        completed=1,
        error="original",
    )

    for attempted_status in attempted_statuses:
        unchanged = store.update_job(
            "job-1",
            status=attempted_status,
            completed=99,
            total=99,
            error="replacement",
        )
        assert unchanged == terminal

    assert store.get_active_job() is None
    assert store.has_market_refresh("hk", "2026-06-29") is has_market_refresh


def test_concurrent_job_updates_write_timestamps_once_and_keep_progress(tmp_path, monkeypatch):
    store = OpportunityStore(tmp_path / "opportunities.db")
    store.create_job(
        job_id="job-1",
        markets=["hk"],
        market_dates={"hk": "2026-06-29"},
        trigger="scheduled",
        total=4,
    )
    clock = threading.local()
    monkeypatch.setattr("src.opportunity_center.storage.utc_now", lambda: clock.value)

    def connect():
        conn = sqlite3.connect(
            store.db_path,
            timeout=5,
            factory=CoordinatedJobConnection,
        )
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(store, "_connect", connect)

    def update(status, completed, timestamp):
        clock.value = timestamp
        return store.update_job("job-1", status=status, completed=completed)

    def update_concurrently(updates):
        CoordinatedJobConnection.read_barrier = threading.Barrier(2)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(update, *args) for args in updates]
                return [future.result(timeout=10) for future in futures]
        finally:
            CoordinatedJobConnection.read_barrier = None

    running_results = update_concurrently(
        [
            ("running", 1, "2026-06-29T10:05:00Z"),
            ("running", 2, "2026-06-29T10:06:00Z"),
        ]
    )
    started_at = {result.started_at for result in running_results}
    assert len(started_at) == 1
    assert None not in started_at
    assert {result.status for result in running_results} == {"running"}
    assert {result.completed for result in running_results} == {1, 2}

    terminal_results = update_concurrently(
        [
            ("failed", 3, "2026-06-29T10:10:00Z"),
            ("completed", 4, "2026-06-29T10:11:00Z"),
        ]
    )
    finished_at = {result.finished_at for result in terminal_results}
    assert len(finished_at) == 1
    assert None not in finished_at
    assert len({result.status for result in terminal_results}) == 1
    assert len({result.completed for result in terminal_results}) == 1

    clock.value = "2026-06-29T10:15:00Z"
    final = store.update_job("job-1", status="completed", completed=5, total=5)
    assert final == terminal_results[0]
    assert final.started_at in started_at
    assert final.finished_at in finished_at


def test_create_job_reuses_existing_active_job_transactionally(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    queued = store.create_job(
        job_id="job-1",
        markets=["hk"],
        market_dates={"hk": "2026-06-29"},
        trigger="scheduled",
        total=1,
    )

    reused_queued = store.create_job(
        job_id="job-2",
        markets=["us"],
        market_dates={"us": "2026-06-28"},
        trigger="manual",
        total=1,
    )
    store.update_job("job-1", status="running")
    reused_running = store.create_job(
        job_id="job-3",
        markets=["us"],
        market_dates={"us": "2026-06-28"},
        trigger="manual",
        total=1,
    )

    assert reused_queued.job_id == queued.job_id
    assert reused_running.job_id == queued.job_id
    assert reused_running.status == "running"
    with store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM refresh_jobs").fetchone()[0]
    assert count == 1


def test_get_active_job_prefers_running_over_newer_queued_row(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    store.create_job(
        job_id="running-job",
        markets=["hk"],
        market_dates={"hk": "2026-06-29"},
        trigger="scheduled",
        total=1,
    )
    store.update_job("running-job", status="running")
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO refresh_jobs (
                job_id, status, markets_json, market_dates_json, trigger,
                completed, total, created_at, updated_at, error
            ) VALUES (?, 'queued', '[]', '{}', 'manual', 0, 1, ?, ?, NULL)
            """,
            ("newer-queued-job", "9999-01-01T00:00:00Z", "9999-01-01T00:00:00Z"),
        )

    active = store.get_active_job()

    assert active is not None
    assert active.job_id == "running-job"
    assert active.status == "running"
