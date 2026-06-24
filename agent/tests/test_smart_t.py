from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.forecast.smart_t import run_smart_t


def _bars(closes: list[float]) -> list[dict[str, object]]:
    dates = pd.bdate_range("2021-01-01", periods=len(closes))
    return [
        {"date": d.strftime("%Y-%m-%d"), "close": float(close), "volume": 1000}
        for d, close in zip(dates, closes)
    ]


def test_smart_t_raises_when_history_is_too_short() -> None:
    with pytest.raises(ValueError, match="insufficient price history"):
        run_smart_t(_bars([100.0] * 20))


def test_smart_t_generates_trades_in_trapped_rebound_market() -> None:
    down = list(np.linspace(100, 72, 80))
    waves = [78, 74, 80, 75, 82, 77, 84, 78, 86, 80] * 10
    recover = list(np.linspace(82, 95, 80))
    out = run_smart_t(_bars(down + waves + recover))

    assert out["summary"]["trade_count"] > 0
    assert out["summary"]["effective_cost"] > 0
    assert "smart_t" in out["metrics"]
    assert out["current_signal"]["action"] in {"观察", "低吸T仓", "高抛止盈", "风控卖出T仓"}
