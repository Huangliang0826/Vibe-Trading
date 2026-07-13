from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.strategy_comparison_routes import register_strategy_comparison_routes
from src.paper_trading.comparison_storage import StrategyComparisonStore


def _client(tmp_path):
    app = FastAPI()
    store = StrategyComparisonStore(tmp_path / "comparisons")
    register_strategy_comparison_routes(
        app, require_auth=lambda: None, store=store,
        executor=lambda _run_id, _store: None,
    )
    return TestClient(app)


def test_create_and_get_comparison(tmp_path):
    client = _client(tmp_path)
    response = client.post("/paper-trading/strategy-comparisons", json={
        "start_date": "2020-01-01", "end_date": "2025-01-02",
        "initial_capital": 100000, "cost_bps": 20,
    })
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert client.get(f"/paper-trading/strategy-comparisons/{run_id}").status_code == 200


def test_short_window_is_rejected(tmp_path):
    response = _client(tmp_path).post("/paper-trading/strategy-comparisons", json={
        "start_date": "2025-01-01", "end_date": "2025-06-01",
    })
    assert response.status_code == 422


def test_unknown_comparison_is_404(tmp_path):
    response = _client(tmp_path).get(
        "/paper-trading/strategy-comparisons/comparison-20250101-000000-deadbeef",
    )
    assert response.status_code == 404
