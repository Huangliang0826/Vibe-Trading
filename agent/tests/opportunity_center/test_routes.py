from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.opportunity_routes import register_opportunity_routes
from src.opportunity_center.models import (
    CalibrationPeriodSummary,
    OpportunityCalibrationSummary,
    OpportunityList,
    RefreshJob,
)


class FakeStore:
    def __init__(self):
        self.jobs = {}

    def get_job(self, job_id):
        return self.jobs.get(job_id)


class FakeService:
    def __init__(self):
        self.store = FakeStore()
        self.detail = None
        self.fail = False

    def get_list(self, **kwargs):
        if self.fail:
            raise RuntimeError("provider offline")
        return OpportunityList(items=[])

    def start_refresh(self, markets, trigger, force=False):
        if self.fail:
            raise RuntimeError("provider offline")
        job = RefreshJob(job_id="job-1", status="queued", markets=markets, trigger=trigger, total=1)
        self.store.jobs[job.job_id] = job
        return job

    async def run_job(self, job_id):
        await asyncio.sleep(0)
        self.store.jobs[job_id] = self.store.jobs[job_id].model_copy(update={"status": "completed"})

    def get_detail(self, market, code, snapshot_date=None):
        return self.detail

    def get_history(self, market, code, limit):
        return []

    def get_calibration(self, scope):
        return OpportunityCalibrationSummary(
            scope=scope,
            periods=[CalibrationPeriodSummary(
                horizon_days=horizon, completed_samples=0,
                pending_samples=0, missing_samples=0,
            ) for horizon in (5, 20, 60)],
        )


class FakeScheduler:
    def start(self):
        pass

    async def stop(self):
        pass


def app(service):
    instance = FastAPI()
    register_opportunity_routes(
        instance, require_auth=lambda: None, service=service,
        scheduler=FakeScheduler(), start_scheduler=False,
    )
    return instance


def test_refresh_returns_json_job():
    service = FakeService()
    with TestClient(app(service)) as client:
        response = client.post("/opportunities/refresh", json={"markets": ["hk"]})
    assert response.status_code == 202
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["status"] == "queued"


def test_static_refresh_route_is_not_consumed_as_market():
    response = TestClient(app(FakeService())).get("/opportunities/refresh/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "opportunity refresh job not found"}


def test_calibration_route_defaults_to_top3_and_accepts_all_scope():
    client = TestClient(app(FakeService()))
    assert client.get("/opportunities/calibration").json()["scope"] == "top3"
    assert client.get("/opportunities/calibration?scope=all").json()["scope"] == "all"
    assert client.get("/opportunities/calibration?scope=invalid").status_code == 422


def test_invalid_market_and_code_are_structured_json():
    client = TestClient(app(FakeService()))
    assert client.get("/opportunities/cn/600000").status_code == 422
    response = client.get("/opportunities/us/../bad")
    assert response.status_code in {400, 404}
    assert response.headers["content-type"].startswith("application/json")


def test_missing_detail_returns_404():
    response = TestClient(app(FakeService())).get("/opportunities/hk/0700")
    assert response.status_code == 404
    assert response.json()["detail"] == "opportunity snapshot not found"


def test_provider_failure_returns_json_detail():
    service = FakeService()
    service.fail = True
    response = TestClient(app(service)).get("/opportunities")
    assert response.status_code == 500
    assert response.json()["detail"] == "opportunity list failed: provider offline"


def test_openapi_contains_opportunity_routes():
    paths = app(FakeService()).openapi()["paths"]
    assert "/opportunities" in paths
    assert "/opportunities/refresh" in paths
    assert "/opportunities/calibration" in paths
