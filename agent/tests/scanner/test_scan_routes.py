from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.scan_routes import register_scan_routes
from src.scanner.core import Candidate, ScanResult


def _app() -> FastAPI:
    app = FastAPI()
    register_scan_routes(app, require_auth=lambda: None)
    return app


def test_get_scan_latest_returns_result(monkeypatch):
    from src.api import scan_routes

    result = ScanResult("sp500", "2026-06-11", ["factor_rank"],
                        [Candidate("AVGO", 92.4, "factor_rank", "top by f1", {})], [])
    monkeypatch.setattr(scan_routes, "load_latest", lambda **kw: result)

    client = TestClient(_app())
    resp = client.get("/scan/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["asof"] == "2026-06-11"
    assert body["candidates"][0]["symbol"] == "AVGO"


def test_get_scan_latest_404_when_empty(monkeypatch):
    from src.api import scan_routes

    monkeypatch.setattr(scan_routes, "load_latest", lambda **kw: None)
    client = TestClient(_app())
    resp = client.get("/scan/latest")
    assert resp.status_code == 404
