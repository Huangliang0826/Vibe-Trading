"""Daily forecast warm-up marker + target collection."""
from __future__ import annotations

import datetime as dt

import api_server
from src.forecast import warmup


def test_needs_warmup_true_when_no_marker(tmp_path):
    assert warmup.needs_warmup(state_path=tmp_path / "m.json") is True


def test_marker_roundtrip_blocks_same_day_and_clears_next_day(tmp_path):
    p = tmp_path / "m.json"
    day = dt.date(2026, 8, 18)
    warmup.mark_warmed(state_path=p, today=day, warmed=25, failed=0)

    assert warmup.needs_warmup(state_path=p, today=day) is False
    assert warmup.needs_warmup(state_path=p, today=day + dt.timedelta(days=1)) is True

    saved = warmup.read_marker(p)
    assert saved["date"] == "2026-08-18"
    assert saved["warmed"] == 25 and saved["failed"] == 0


def test_corrupt_marker_is_treated_as_not_warmed(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("not json", encoding="utf-8")
    assert warmup.read_marker(p) == {}
    assert warmup.needs_warmup(state_path=p) is True


def test_warm_targets_cover_every_market(monkeypatch):
    class FakeStore:
        def get(self, market):
            return {"cn": ["300750"], "hk": ["00700", "1810"], "us": ["AAPL"]}[market]

    monkeypatch.setattr(api_server, "_get_watchlist_store", lambda: FakeStore())
    assert api_server._forecast_warm_targets() == [
        ("cn", "300750"), ("hk", "00700"), ("hk", "1810"), ("us", "AAPL"),
    ]


def test_warm_targets_survive_a_failing_market(monkeypatch):
    class FlakyStore:
        def get(self, market):
            if market == "hk":
                raise RuntimeError("watchlist unavailable")
            return {"cn": [], "us": ["AAPL"]}[market]

    monkeypatch.setattr(api_server, "_get_watchlist_store", lambda: FlakyStore())
    assert api_server._forecast_warm_targets() == [("us", "AAPL")]


def test_warm_once_passes_real_values_not_query_objects(monkeypatch):
    """Calling endpoint functions directly bypasses FastAPI's dependency
    resolution, so every Query-defaulted argument must be passed explicitly —
    otherwise a ``Query`` object reaches the handler and it fails at runtime."""
    import asyncio

    from fastapi import params

    class FakeStore:
        def get(self, market):
            return {"cn": [], "hk": [], "us": ["AAPL"]}[market]

    seen = []

    async def fake_forecast(*args, **kwargs):
        seen.extend([*args, *kwargs.values()])
        return {}

    async def fake_strategy(*args, **kwargs):
        seen.extend([*args, *kwargs.values()])
        return {}

    monkeypatch.setattr(api_server, "_get_watchlist_store", lambda: FakeStore())
    monkeypatch.setattr(api_server, "get_forecast", fake_forecast)
    monkeypatch.setattr(api_server, "get_forecast_best_paper_strategy", fake_strategy)

    warmed, failed = asyncio.run(api_server._warm_forecasts_once())

    assert (warmed, failed) == (1, 0)
    offenders = [a for a in seen if isinstance(a, params.Query)]
    assert not offenders, f"unresolved Query defaults leaked into the call: {offenders}"


def test_warm_once_isolates_a_failing_symbol(monkeypatch):
    import asyncio

    class FakeStore:
        def get(self, market):
            return {"cn": [], "hk": ["1810"], "us": ["AAPL"]}[market]

    async def flaky_forecast(market, code, **kwargs):
        if code == "1810":
            raise RuntimeError("data source down")
        return {}

    async def ok_strategy(*args, **kwargs):
        return {}

    monkeypatch.setattr(api_server, "_get_watchlist_store", lambda: FakeStore())
    monkeypatch.setattr(api_server, "get_forecast", flaky_forecast)
    monkeypatch.setattr(api_server, "get_forecast_best_paper_strategy", ok_strategy)

    # One bad symbol is counted and skipped; the rest still warm.
    assert asyncio.run(api_server._warm_forecasts_once()) == (1, 1)
