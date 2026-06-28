"""Lock the split/dividend adjustment flags on the two US-equity loaders."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd


def test_yfinance_download_requests_adjusted_prices():
    captured = {}

    def fake_download(*args, **kwargs):
        captured.update(kwargs)
        idx = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03"]))
        return pd.DataFrame(
            {"Open": [1.0, 1.0], "High": [1.0, 1.0], "Low": [1.0, 1.0],
             "Close": [1.0, 1.0], "Volume": [10, 10]},
            index=idx,
        )

    with patch("backtest.loaders.yfinance_loader.yf.download", side_effect=fake_download):
        from backtest.loaders.yfinance_loader import _download_history

        _download_history("AAPL", "2024-01-01", "2024-01-04", "1d")

    assert captured.get("auto_adjust") is True, (
        "yfinance must auto-adjust for splits/dividends; raw Close leaks false "
        "pct_change jumps on split days"
    )
    assert captured.get("end") == "2024-01-05", (
        "the loader contract treats end_date as inclusive, while yfinance end is exclusive"
    )


def test_alpaca_bars_request_uses_full_adjustment():
    import sys
    import types

    captured = {}

    class FakeStockBarsRequest:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class FakeTimeFrame:
        def __init__(self, amount, unit):
            self.amount = amount
            self.unit = unit

    class FakeTimeFrameUnit:
        Day = "Day"
        Hour = "Hour"
        Minute = "Minute"

    fake_requests = types.ModuleType("alpaca.data.requests")
    fake_requests.StockBarsRequest = FakeStockBarsRequest
    fake_exc = types.ModuleType("alpaca.common.exceptions")
    fake_exc.APIError = type("APIError", (Exception,), {})
    fake_timeframe = types.ModuleType("alpaca.data.timeframe")
    fake_timeframe.TimeFrame = FakeTimeFrame
    fake_timeframe.TimeFrameUnit = FakeTimeFrameUnit

    from backtest.loaders import alpaca_loader

    loader = alpaca_loader.DataLoader.__new__(alpaca_loader.DataLoader)
    loader._client = lambda: MagicMock(get_stock_bars=lambda req: MagicMock(data={}))
    loader._feed = lambda: "iex"

    with patch.dict(sys.modules, {
        "alpaca.data.requests": fake_requests,
        "alpaca.common.exceptions": fake_exc,
        "alpaca.data.timeframe": fake_timeframe,
    }):
        loader._fetch_bars(["AAPL"], "2024-01-01", "2024-01-04", "1D")

    assert str(captured.get("adjustment")).lower().endswith("all") or \
        captured.get("adjustment") == "all", (
        "alpaca bars must request split+dividend adjustment ('all'); SDK default "
        "is 'raw' which leaks false jumps on split days"
    )
