from __future__ import annotations

from datetime import date

import pandas as pd

import api_server


def test_df_to_bars_preserves_ohlc_and_nullable_volume():
    frame = pd.DataFrame(
        {"open": [99.0], "high": [102.0], "low": [98.0], "close": [101.0], "volume": [None]},
        index=pd.to_datetime(["2026-01-02"]),
    )

    assert api_server._df_to_bars(frame, intraday=False) == [{
        "date": "2026-01-02",
        "open": 99.0,
        "high": 102.0,
        "low": 98.0,
        "close": 101.0,
        "volume": None,
    }]


def test_history_payload_exposes_canonical_metrics_contract():
    payload = api_server._build_history_metrics_payload(
        code="AAPL",
        name="Apple",
        market="us",
        period="1Y",
        requested_start=date(2025, 1, 3),
        source="fixture",
        bars=[
            {"date": "2025-01-02", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1_000},
            {"date": "2025-01-03", "open": 110, "high": 110, "low": 110, "close": 110, "volume": None},
            {"date": "2025-01-06", "open": 121, "high": 121, "low": 121, "close": 121, "volume": 1_200},
        ],
    )

    assert payload["formula_version"] == "market-metrics-v1"
    assert payload["adjustment"] == "adjusted"
    assert payload["baseline"]["date"] == "2025-01-02"
    assert payload["metrics"]["interval_return_pct"] == 21.0
    assert payload["metrics"]["dca_contribution_count"] == 2
    assert payload["bars"][1]["volume"] is None
    assert payload["data_status"]["quality"] == "warning"


def test_non_positive_adjusted_a_share_data_is_not_replaced_with_raw(monkeypatch):
    adjusted = pd.DataFrame(
        {"open": [-1.0], "high": [-1.0], "low": [-1.0], "close": [-1.0], "volume": [1_000]},
        index=pd.to_datetime(["2026-01-02"]),
    )

    class Loader:
        def fetch(self, **_kwargs):
            return {"600519": adjusted}

    monkeypatch.setattr("backtest.loaders.registry.resolve_loader", lambda _market: Loader())
    monkeypatch.setattr(api_server, "_resolve_symbol_name", lambda *_args: "贵州茅台")
    monkeypatch.setattr(
        api_server,
        "_cn_raw_daily",
        lambda *_args: (_ for _ in ()).throw(AssertionError("raw fallback must not run")),
    )

    result = api_server._fetch_price_history("600519", "ALL", "cn")

    assert result["adjustment"] == "adjusted"
    assert result["bars"][0]["close"] == -1.0


def test_csi300_alias_uses_canonical_index_code_for_history(monkeypatch):
    frame = pd.DataFrame(
        {"open": [4800.0], "high": [4850.0], "low": [4780.0], "close": [4820.0], "volume": [1_000]},
        index=pd.to_datetime(["2026-07-03"]),
    )
    requested_codes: list[str] = []

    class Loader:
        def fetch(self, *, codes, **_kwargs):
            requested_codes.extend(codes)
            return {"000300.SS": frame}

    monkeypatch.setattr("backtest.loaders.yfinance_loader.DataLoader", Loader)
    monkeypatch.setattr(
        "backtest.loaders.registry.resolve_loader",
        lambda _market: (_ for _ in ()).throw(AssertionError("index must not use the stock loader")),
    )
    monkeypatch.setattr(api_server, "_resolve_symbol_name", lambda *_args: "沪深300")

    result = api_server._fetch_price_history("399300", "ALL", "cn")

    assert requested_codes == ["000300.SS"]
    assert result["bars"][0]["close"] == 4820.0


def test_csi300_alias_uses_canonical_index_code_for_quote(monkeypatch):
    requested_codes: list[str] = []

    def fake_fetch_quote(codes):
        requested_codes.extend(codes)
        raise AssertionError("index must not use the stock quote loader")

    monkeypatch.setattr("backtest.loaders.a_stock_data_research.fetch_quote", fake_fetch_quote)
    monkeypatch.setattr(api_server, "_fetch_cn_indices", lambda: [{
        "code": "sh000300",
        "name": "沪深300",
        "market": "A股",
        "price": 4820.0,
        "change_pct": 0.5,
        "prev_close": 4796.0,
    }])

    result = api_server._fetch_cn_watchlist_quotes(["399300"])

    assert requested_codes == []
    assert result == [{
        "code": "399300",
        "name": "沪深300",
        "price": 4820.0,
        "change_pct": 0.5,
        "prev_close": 4796.0,
    }]
