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

