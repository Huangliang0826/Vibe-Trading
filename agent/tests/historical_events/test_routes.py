from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.historical_event_routes import register_historical_event_routes
from src.historical_events.models import HistoricalEventRun


class FakeService:
    def start_run(self, market, code, company_name, period, force=False):
        return HistoricalEventRun(run_id="run-1", market=market, symbol=code, company_name=company_name, period=period)

    def run(self, run_id):
        return None

    def get_run(self, run_id):
        return HistoricalEventRun(run_id=run_id, market="hk", symbol="0700", company_name="腾讯控股", period="1Y")

    def list_events(self, market, code, period):
        return []


def client() -> TestClient:
    app = FastAPI()
    register_historical_event_routes(app, require_auth=lambda: None, service=FakeService())
    return TestClient(app)


def test_create_run_returns_structured_job():
    response = client().post("/historical-events/runs", json={
        "market": "hk", "code": "0700", "company_name": "腾讯控股", "period": "1Y",
    })

    assert response.status_code == 202
    assert response.json()["run_id"] == "run-1"


def test_get_events_supports_a_shares():
    response = client().get("/historical-events/cn/600519?period=1Y")

    assert response.status_code == 200
