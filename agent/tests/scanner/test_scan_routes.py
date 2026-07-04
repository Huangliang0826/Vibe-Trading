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


def test_scan_latest_passes_selected_universe(monkeypatch):
    from src.api import scan_routes

    seen = []
    result = ScanResult("hstech", "2026-07-01", [], [], [])
    monkeypatch.setattr(
        scan_routes, "load_latest", lambda universe: seen.append(universe) or result
    )

    resp = TestClient(_app()).get("/scan/latest?universe=hstech")

    assert resp.status_code == 200
    assert seen == ["hstech"]
    assert resp.json()["universe"] == "hstech"


def test_scan_dates_passes_selected_universe(monkeypatch):
    from src.api import scan_routes

    seen = []
    monkeypatch.setattr(
        scan_routes, "list_scan_dates", lambda universe: seen.append(universe) or ["2026-07-01"]
    )

    resp = TestClient(_app()).get("/scan/dates?universe=hstech")

    assert resp.status_code == 200
    assert seen == ["hstech"]


def test_scan_routes_reject_a_share_universe():
    resp = TestClient(_app()).get("/scan/latest?universe=csi300")

    assert resp.status_code == 400


def test_scan_routes_reject_unknown_universe():
    resp = TestClient(_app()).get("/scan/latest?universe=unknown")

    assert resp.status_code == 400
    assert "universe" in resp.json()["detail"]


def test_scan_tracking_backfills_missing_records_from_saved_scan(monkeypatch):
    from src.api import scan_routes
    from src.scanner.tracking import TrackingRecord

    result = ScanResult(
        "hstech", "2026-07-01", ["factor_rank"],
        [Candidate("0700.HK", 92.4, "factor_rank", "top", {})], [],
    )
    seen = []
    monkeypatch.setattr(scan_routes, "load_tracking", lambda *args, **kwargs: [])
    monkeypatch.setattr(scan_routes, "load_by_date", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        scan_routes,
        "backfill_returns",
        lambda asof, candidates, universe: seen.append((asof, candidates, universe)) or [
            TrackingRecord("0700.HK", 92.4, asof, fwd_1d=1.25)
        ],
    )

    resp = TestClient(_app()).get("/scan/tracking/2026-07-01?universe=hstech")

    assert resp.status_code == 200
    assert resp.json()["records"][0]["fwd_1d"] == 1.25
    assert seen == [("2026-07-01", [result.candidates[0].to_dict()], "hstech")]
