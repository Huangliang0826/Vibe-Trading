from __future__ import annotations

from fastapi.testclient import TestClient

import api_server
from src.paper_trading import hstech_best


def _selection() -> dict:
    return {
        "selection_version": "single-symbol-robust-oos-v1",
        "selected_strategy": "donchian_breakout",
        "reliable": True,
        "training_end": "2025-07-01",
        "oos_validation": {"passed": True, "metrics": {"sharpe": 0.8}},
        "robust_result": {"strategies": []},
    }


def _daily(end_date: str, selection: dict) -> dict:
    return {
        "code": "NVDA", "name": "NVIDIA", "market": "us",
        "start_date": "2006-07-03", "end_date": end_date,
        "initial_total_usd": 100000, "best": {"strategy": {"name": selection["selected_strategy"]}, "trades": []},
        "candidates": [], "summary": "robust", "selection": selection,
        "oos_validation": selection["oos_validation"], "reliable": True,
        "signal_as_of": end_date,
    }


def test_forecast_reuses_annual_selection_but_refreshes_daily_signal(monkeypatch, tmp_path):
    select_calls = []
    daily_calls = []

    def fake_select(*args, **kwargs):
        select_calls.append((args, kwargs))
        return _selection()

    def fake_daily(*args, **kwargs):
        daily_calls.append((args, kwargs))
        return _daily(kwargs["end_date"], kwargs["selection"])

    monkeypatch.setattr(hstech_best, "select_single_symbol_robust_strategy", fake_select)
    monkeypatch.setattr(hstech_best, "run_selected_single_symbol_strategy", fake_daily)
    monkeypatch.setattr(api_server, "_resolve_symbol_name", lambda code, market: "NVIDIA")
    monkeypatch.setattr(api_server, "_BEST_STRATEGY_DISK_CACHE_DIR", tmp_path)
    api_server._ROBUST_SELECTION_CACHE.clear()
    api_server._HSTECH_BEST_STRATEGY_CACHE.clear()
    client = TestClient(api_server.app)

    first = client.get("/forecast/us/NVDA/best-paper-strategy?end_date=2026-07-01")
    second = client.get("/forecast/us/NVDA/best-paper-strategy?end_date=2026-07-02")
    refreshed = client.get("/forecast/us/NVDA/best-paper-strategy?end_date=2026-07-02&refresh=true")

    assert first.status_code == second.status_code == refreshed.status_code == 200
    assert len(select_calls) == 2
    assert len(daily_calls) == 3
    assert second.json()["selection_cached"] is True
    assert second.json()["signal_cached"] is False
    assert refreshed.json()["selection_cached"] is False
