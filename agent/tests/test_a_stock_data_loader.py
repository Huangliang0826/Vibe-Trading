"""Tests for the a_stock_data A-share OHLCV loader (no network)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.loaders.a_stock_data import DataLoader, _is_a_share, _is_bj


# ---------------------------------------------------------------------------
# Symbol detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, expected",
    [
        ("000001.SZ", True), ("600519.SH", True), ("835174.BJ", True),
        ("000001", True), ("600519", True),
        ("AAPL.US", False), ("00700.HK", False), ("BTC-USDT", False),
        ("12345", False), ("000001A", False),
    ],
)
def test_is_a_share(code: str, expected: bool) -> None:
    assert _is_a_share(code) is expected


@pytest.mark.parametrize(
    "code, expected",
    [("835174.BJ", True), ("832000", True), ("488888", True),
     ("000001.SZ", False), ("600519", False), ("300750", False)],
)
def test_is_bj(code: str, expected: bool) -> None:
    assert _is_bj(code) is expected


# ---------------------------------------------------------------------------
# Baidu daily path (primary)
# ---------------------------------------------------------------------------


def _baidu_payload() -> dict:
    """Mimic finance.pae.baidu.com newMarketData (keys + ';'-joined rows)."""
    keys = ["time", "open", "close", "high", "low", "volume", "amount",
            "ma5avgprice", "ma10avgprice", "ma20avgprice"]
    rows = [
        "2025-01-02,11.73,11.43,11.77,11.40,1000000,1.1e7,11.5,11.4,11.3",
        "2025-01-03,11.44,11.38,11.54,11.32,800000,9.1e6,11.5,11.4,11.3",
        "2025-01-06,11.38,11.44,11.48,11.31,950000,1.08e7,11.5,11.4,11.3",
    ]
    return {"Result": {"newMarketData": {"keys": keys, "rows": rows,
                                          "marketData": ";".join(rows)}}}


@pytest.fixture
def fake_baidu(monkeypatch: pytest.MonkeyPatch):
    """Patch requests.get used inside the loader to return a Baidu payload."""
    calls: list[tuple] = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        calls.append((url, params))
        return SimpleNamespace(json=lambda: _baidu_payload())

    import backtest.loaders.a_stock_data as mod
    monkeypatch.setattr(mod.requests, "get", fake_get)
    return calls


def test_fetch_daily_uses_baidu(fake_baidu) -> None:
    loader = DataLoader()
    out = loader.fetch(["000001.SZ"], "2025-01-01", "2025-01-10", interval="1D")

    assert "000001.SZ" in out
    df = out["000001.SZ"]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "trade_date"
    assert len(df) == 3
    # Baidu was queried with the bare 6-digit code.
    assert fake_baidu and fake_baidu[0][1]["code"] == "000001"


def test_fetch_daily_clips_window(fake_baidu) -> None:
    loader = DataLoader()
    out = loader.fetch(["600519"], "2025-01-03", "2025-01-03", interval="1D")
    df = out["600519"]
    assert len(df) == 1
    assert str(df.index[0].date()) == "2025-01-03"


# ---------------------------------------------------------------------------
# Symbol skipping
# ---------------------------------------------------------------------------


def test_fetch_skips_non_a_share(fake_baidu) -> None:
    loader = DataLoader()
    out = loader.fetch(["AAPL.US", "00700.HK", "BTC-USDT"], "2025-01-01", "2025-01-10")
    assert out == {}
    assert fake_baidu == []


def test_fetch_skips_bj_with_warning(fake_baidu, caplog: pytest.LogCaptureFixture) -> None:
    import logging
    caplog.set_level(logging.WARNING)
    loader = DataLoader()
    out = loader.fetch(["835174.BJ", "832000", "000001.SZ"], "2025-01-01", "2025-01-10")
    assert "835174.BJ" not in out and "832000" not in out
    assert "000001.SZ" in out
    assert len([r for r in caplog.records if "北交所" in r.message]) == 2


# ---------------------------------------------------------------------------
# Baidu failure -> mootdx fallback
# ---------------------------------------------------------------------------


def test_daily_falls_back_to_mootdx_when_baidu_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import backtest.loaders.a_stock_data as mod

    # Baidu returns an empty payload.
    monkeypatch.setattr(
        mod.requests, "get",
        lambda *a, **k: SimpleNamespace(json=lambda: {"Result": {"newMarketData": {}}}),
    )

    # Stub the mootdx loader the a_stock_data loader delegates to.
    fb = pd.DataFrame(
        {"open": [10.0], "high": [10.5], "low": [9.5], "close": [10.2], "volume": [123.0]},
        index=pd.DatetimeIndex(["2025-01-02"], name="trade_date"),
    )
    captured: list[tuple] = []

    class _FakeMootdx:
        def _fetch_one(self, symbol, start_date, end_date, interval):
            captured.append((symbol, interval))
            return fb

    monkeypatch.setattr(DataLoader, "_mootdx_loader", lambda self: _FakeMootdx())

    out = DataLoader().fetch(["000001.SZ"], "2025-01-01", "2025-01-10", interval="1D")
    assert "000001.SZ" in out
    assert captured == [("000001", "1D")]  # delegated with bare code


def test_intraday_delegates_to_mootdx(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = pd.DataFrame(
        {"open": [1.0], "high": [1.1], "low": [0.9], "close": [1.05], "volume": [10.0]},
        index=pd.DatetimeIndex(["2025-01-02 09:30"], name="trade_date"),
    )
    seen: list[tuple] = []

    class _FakeMootdx:
        def _fetch_one(self, symbol, start_date, end_date, interval):
            seen.append((symbol, interval))
            return bars

    monkeypatch.setattr(DataLoader, "_mootdx_loader", lambda self: _FakeMootdx())
    out = DataLoader().fetch(["600519"], "2025-01-02", "2025-01-02", interval="15m")
    assert "600519" in out
    assert seen == [("600519", "15m")]


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_is_available_true_when_mootdx_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "mootdx", SimpleNamespace())
    assert DataLoader().is_available() is True


def test_is_available_false_when_mootdx_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name == "mootdx" or name.startswith("mootdx."):
            raise ImportError("mootdx not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)
    assert DataLoader().is_available() is False


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_registry_lists_a_stock_data_at_chain_head() -> None:
    from backtest.loaders.registry import FALLBACK_CHAINS, LOADER_REGISTRY, _ensure_registered

    _ensure_registered()
    assert "a_stock_data" in LOADER_REGISTRY
    chain = FALLBACK_CHAINS["a_share"]
    assert chain[0] == "a_stock_data"
    # Existing sources preserved as fallbacks.
    for src in ("tushare", "mootdx", "akshare"):
        assert src in chain


def test_runner_accepts_a_stock_data_source() -> None:
    from backtest.runner import BacktestConfigSchema

    cfg = BacktestConfigSchema(
        codes=["000001.SZ"], start_date="2025-01-02", end_date="2025-03-01",
        source="a_stock_data", interval="1D",
    )
    assert cfg.source == "a_stock_data"


def test_create_market_engine_routes_a_stock_data_to_china_a() -> None:
    from backtest.engines.china_a import ChinaAEngine
    from backtest.runner import _create_market_engine

    engine = _create_market_engine("a_stock_data", {}, ["000001.SZ"])
    assert isinstance(engine, ChinaAEngine)
