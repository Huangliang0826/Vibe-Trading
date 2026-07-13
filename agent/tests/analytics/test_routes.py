from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.analytics.collector import AnalyticsCollector
from src.analytics.rollup import AnalyticsRollup
from src.analytics.service import AnalyticsService
from src.analytics.store import AnalyticsStore
from src.api.analytics_routes import register_analytics_routes


def _client(tmp_path):
    app = FastAPI()
    store = AnalyticsStore(tmp_path / "a.db")
    service = AnalyticsService(store, AnalyticsCollector(store), AnalyticsRollup(store))
    register_analytics_routes(app, require_auth=lambda: None, service=service)
    return TestClient(app), store


def test_event_batch_and_empty_trend_contract(tmp_path):
    client, store = _client(tmp_path)
    payload = {
        "events": [
            {
                "event_id": "web-1",
                "kind": "product",
                "occurred_at": "2026-07-13T09:00:00Z",
                "workspace_id": "local",
                "user_id": "u",
                "feature": "scanner",
                "action": "page_view",
                "outcome": "success",
                "metadata": {"route": "/scanner"},
            }
        ]
    }
    response = client.post("/api/analytics/events", json=payload)
    assert response.status_code == 202
    assert response.json() == {"accepted": 1, "rejected": 0, "dropped": 0}
    assert len(store.query_events(kind="product")) == 0
    response = client.get("/api/analytics/trends?metric=page_views&days=30")
    assert response.status_code == 200
    assert response.json()["points"] == []
    assert response.json()["warnings"] == ["no_data"]
