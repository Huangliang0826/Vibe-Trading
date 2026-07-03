from __future__ import annotations

import pandas as pd
import pytest

from src.paper_trading.robust import _build_windows, _common_data_span, _history_start_date
from src.paper_trading.models import RobustOptimizeCreate


def _frame(start: str, end: str) -> pd.DataFrame:
    index = pd.bdate_range(start, end)
    return pd.DataFrame({"close": range(1, len(index) + 1)}, index=index)


def test_history_start_date_caps_fetch_at_twenty_years() -> None:
    assert _history_start_date("2026-07-02") == "2006-07-02"


def test_robust_request_does_not_require_a_start_date() -> None:
    request = RobustOptimizeCreate.model_validate({
        "holdings": [{"symbol": "NVDA", "market": "us", "allocation_pct": 100}],
        "strategies": [{"name": "buy_and_hold", "params": {}}],
        "end_date": "2026-07-02",
    })

    assert request.start_date is None
    assert request.step_years == 1


def test_three_year_windows_roll_forward_every_year_without_dropping_early_periods() -> None:
    windows = _build_windows(
        pd.Timestamp("2006-07-02"), pd.Timestamp("2026-07-02"),
        window_years=3, step_years=1,
    )
    labels = [window["label"] for window in windows]

    assert labels[:3] == ["2006–2009", "2007–2010", "2008–2011"]
    assert "2012–2015" in labels
    assert "2013–2016" in labels
    assert labels[-1] == "全历史"
    assert len(labels) == 19


def test_common_data_span_uses_latest_listing_and_earliest_last_date() -> None:
    data = {
        "OLD": _frame("2006-07-03", "2026-07-02"),
        "NEW": _frame("2021-03-15", "2026-07-01"),
    }

    start, end, limiting = _common_data_span(data, ["OLD", "NEW"])

    assert start == pd.Timestamp("2021-03-15")
    assert end == pd.Timestamp("2026-07-01")
    assert limiting == ["NEW"]


def test_common_data_span_rejects_missing_portfolio_symbols() -> None:
    with pytest.raises(ValueError, match="MISSING"):
        _common_data_span({"OLD": _frame("2020-01-01", "2026-01-01")}, ["OLD", "MISSING"])
