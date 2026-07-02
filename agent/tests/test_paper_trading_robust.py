from __future__ import annotations

import pandas as pd
import pytest

from src.paper_trading.robust import _common_data_span, _history_start_date
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
