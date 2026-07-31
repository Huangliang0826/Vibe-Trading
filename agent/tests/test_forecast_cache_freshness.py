"""The forecast cone cache must roll over with the trading date.

Regression guard for the cone-vs-signal divergence: the cone key used to omit
the date, so it could serve a payload up to _FORECAST_TTL old while the
strategy-signal cache (keyed on the trading date) moved on, dropping the newest
markers off the chart. All forecast-surface caches now key on
``default_end_date()``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import api_server
from src.forecast import service
from src.paper_trading import hstech_best


def _install(monkeypatch, tmp_path):
    build_calls = {"n": 0}

    def fake_history(code, period, market):  # noqa: ANN001
        return {"name": code, "bars": [{"date": "2026-07-30", "close": 10.0, "volume": 1}]}

    def fake_build(bars, horizon, with_model, context, display_history):  # noqa: ANN001
        build_calls["n"] += 1
        return {"horizon": horizon, "history": bars, "future_dates": [], "model": None,
                "baselines": {"random_walk": [], "drift": []}}

    monkeypatch.setattr(api_server, "_fetch_price_history", fake_history)
    monkeypatch.setattr(service, "build_forecast", fake_build)
    monkeypatch.setattr(api_server, "_FORECAST_DISK_CACHE_DIR", tmp_path)
    api_server._FORECAST_CACHE.clear()
    return build_calls


def test_cone_cache_hits_within_a_day_but_rolls_over_next_day(monkeypatch, tmp_path):
    build_calls = _install(monkeypatch, tmp_path)
    client = TestClient(api_server.app)

    monkeypatch.setattr(hstech_best, "default_end_date", lambda: "2026-07-30")
    first = client.get("/forecast/us/AAPL")
    second = client.get("/forecast/us/AAPL")  # same day → cache hit, no rebuild

    assert first.status_code == second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert build_calls["n"] == 1

    # New trading day → key changes → cache miss → rebuild.
    monkeypatch.setattr(hstech_best, "default_end_date", lambda: "2026-07-31")
    third = client.get("/forecast/us/AAPL")

    assert third.status_code == 200
    assert third.json()["cached"] is False
    assert build_calls["n"] == 2
