from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.analytics.collector import AnalyticsCollector
from src.analytics.edge import EDGE_SPECS, evaluate_edge
from src.analytics.quality import make_quality_event
from src.analytics.rollup import AnalyticsRollup
from src.analytics.service import AnalyticsService
from src.analytics.store import AnalyticsStore
from src.api.analytics_routes import register_analytics_routes


def client(tmp_path):
    app = FastAPI()
    store = AnalyticsStore(tmp_path / "a.db")
    service = AnalyticsService(store, AnalyticsCollector(store), AnalyticsRollup(store))
    register_analytics_routes(app, require_auth=lambda: None, service=service)
    return TestClient(app), store


def seed(store, *, subject, metric, market, horizon, value, n, low=None, high=None, subject_id="all"):
    store.append_events([make_quality_event(
        subject_type=subject, subject_id=subject_id, market=market, horizon=horizon,
        regime="all", metric_name=metric, metric_value=value, sample_count=n,
        formula_version=f"{subject}.v1", as_of=date.today(),
        interval_low=low, interval_high=high,
    )])


# ── verdict logic ────────────────────────────────────────────────────────────

def test_scanner_edge_when_net_interval_clears_zero():
    spec = EDGE_SPECS["scanner"]
    # spread 2.0%, interval [1.0, 3.0]; 15bps × 2 legs = 0.30% cost → net_low 0.70 > 0
    a = evaluate_edge(spec, value=2.0, interval_low=1.0, interval_high=3.0, sample_count=200, cost_bps=15.0)
    assert a.verdict == "edge"
    assert a.confidence == "significant"
    assert round(a.cost_applied, 2) == 0.30


def test_scanner_no_edge_when_cost_eats_the_interval():
    spec = EDGE_SPECS["scanner"]
    # spread 0.2%, interval [0.1, 0.3]; cost 0.30% → net_low negative → not demonstrated
    a = evaluate_edge(spec, value=0.2, interval_low=0.1, interval_high=0.3, sample_count=200, cost_bps=15.0)
    assert a.verdict == "no_edge"


def test_forecast_edge_needs_interval_above_half():
    spec = EDGE_SPECS["forecast"]
    assert evaluate_edge(spec, value=0.6, interval_low=0.55, interval_high=0.65, sample_count=100, cost_bps=15).verdict == "edge"
    # straddles 0.5 → no edge; and no cost haircut on an accuracy
    assert evaluate_edge(spec, value=0.52, interval_low=0.47, interval_high=0.57, sample_count=100, cost_bps=15).verdict == "no_edge"


def test_insufficient_sample():
    spec = EDGE_SPECS["scanner"]
    a = evaluate_edge(spec, value=5.0, interval_low=4.0, interval_high=6.0, sample_count=5, cost_bps=15)
    assert a.verdict == "insufficient"


def test_paper_trading_point_estimate_uses_sharpe_bar():
    spec = EDGE_SPECS["paper_trading"]
    assert evaluate_edge(spec, value=0.8, interval_low=None, interval_high=None, sample_count=50, cost_bps=15).verdict == "edge"
    assert evaluate_edge(spec, value=0.3, interval_low=None, interval_high=None, sample_count=50, cost_bps=15).verdict == "no_edge"
    a = evaluate_edge(spec, value=0.8, interval_low=None, interval_high=None, sample_count=50, cost_bps=15)
    assert a.confidence == "point_estimate"


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_edge_scorecard_endpoint_pools_forecast_and_ranks(tmp_path):
    c, store = client(tmp_path)
    # scanner: strong edge
    seed(store, subject="scanner", metric="top_bottom_spread_pct", market="us", horizon="5d",
         value=2.5, n=300, low=1.5, high=3.5)
    # forecast: two stocks pooled → overall ~0.6 with tight interval → edge
    seed(store, subject="forecast", metric="directional_accuracy", market="us", horizon="63d",
         value=0.60, n=150, subject_id="AAPL")
    seed(store, subject="forecast", metric="directional_accuracy", market="us", horizon="63d",
         value=0.62, n=150, subject_id="MSFT")

    body = c.get("/api/analytics/edge-scorecard?days=90&cost_bps=15").json()
    assert body["cost_bps"] == 15
    rows = body["rows"]
    # forecast rows are pooled per market/horizon (one row, subject_id "pooled")
    forecast_rows = [r for r in rows if r["source"] == "forecast"]
    assert len(forecast_rows) == 1
    assert forecast_rows[0]["subject_id"] == "pooled"
    assert forecast_rows[0]["sample_count"] == 300  # pooled 150 + 150
    # scanner edge present
    scanner = [r for r in rows if r["source"] == "scanner"][0]
    assert scanner["verdict"] == "edge"
    assert scanner["gross_value"] == 2.5
    assert scanner["value"] < 2.5  # cost applied
    # summary counts + edges sorted first
    assert body["summary"]["edge"] >= 1
    assert rows[0]["verdict"] == "edge"
