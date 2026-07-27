from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.analytics.collector import AnalyticsCollector
from src.analytics.models import SourceSyncState
from src.analytics.quality import make_quality_event
from src.analytics.rollup import AnalyticsRollup
from src.analytics.service import AnalyticsService
from src.analytics.store import AnalyticsStore
from src.api.analytics_routes import register_analytics_routes


def research_client(tmp_path):
    app = FastAPI()
    store = AnalyticsStore(tmp_path / "a.db")
    service = AnalyticsService(store, AnalyticsCollector(store), AnalyticsRollup(store))
    register_analytics_routes(app, require_auth=lambda: None, service=service)
    return TestClient(app), store


def seed_quality(store, *, subject, market, horizon, metric, value, sample_count, as_of=None):
    # Default to today so freshness (≤2d) and coverage (30d window) stay valid
    # over time — a hardcoded date silently rots the suite.
    store.append_events([make_quality_event(
        subject_type=subject, subject_id="all", market=market, horizon=horizon,
        regime="all", metric_name=metric, metric_value=value, sample_count=sample_count,
        formula_version=f"{subject}.v1", as_of=as_of or date.today(),
    )])


def test_research_api_filters_and_reports_insufficient_samples(tmp_path):
    client, store = research_client(tmp_path)
    seed_quality(store, subject="scanner", market="us", horizon="5d", metric="hit_rate", value=0.57, sample_count=21)
    seed_quality(store, subject="forecast", market="us", horizon="63d", metric="directional_accuracy", value=0.55, sample_count=2)
    scanner = client.get("/api/analytics/research-quality?days=30&subject=scanner&market=us&horizon=5d").json()
    assert scanner["series"][0]["sample_count"] == 21
    assert scanner["series"][0]["interval_low"] is not None
    forecast = client.get("/api/analytics/research-quality?days=30&subject=forecast&market=us&horizon=63d").json()
    assert forecast["status"] == "insufficient_sample"
    assert forecast["value"] is None


def test_research_api_reports_source_coverage_and_freshness(tmp_path):
    client, store = research_client(tmp_path)
    seed_quality(
        store,
        subject="scanner",
        market="us",
        horizon="5d",
        metric="hit_rate",
        value=0.57,
        sample_count=21,
    )
    today = date.today().isoformat()
    store.upsert_source_state(SourceSyncState(
        source="scanner",
        status="available",
        last_attempted_at=f"{today}T10:00:00Z",
        last_success_at=f"{today}T10:00:00Z",
        data_through=today,
        records_scanned=21,
        events_written=1,
        coverage_days=1,
    ))

    body = client.get(
        "/api/analytics/research-quality?days=30&subject=scanner&market=us&horizon=5d"
    ).json()

    assert body["freshness"] == "fresh"
    assert body["coverage"]["window_days"] == 30
    assert body["coverage"]["covered_days"] == 1
    assert body["coverage"]["coverage_rate"] == 1 / 30
    assert body["coverage"]["sources"][0]["source"] == "scanner"
