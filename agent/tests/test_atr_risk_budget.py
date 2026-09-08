"""ATR risk-budget strategy: sizing is driven by measured risk, never by a
direction call. These tests pin the properties that make it a risk allocator
rather than another timing model."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.paper_trading.models import PaperHolding
from src.paper_trading.strategies import generate_atr_risk_budget


def _frame(closes, spread=1.0):
    idx = pd.date_range("2022-01-03", periods=len(closes), freq="B")
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({
        "open": close, "high": close + spread, "low": close - spread,
        "close": close, "volume": 1_000_000,
    }, index=idx)


HOLD = [PaperHolding(symbol="X", market="us", allocation_pct=100.0)]
CODE = "X.US"   # _to_code() suffixes US symbols


def _run(frame, **params):
    return generate_atr_risk_budget(HOLD, {CODE: frame}, params)[CODE]


def _steady(n=400, start=100.0, step=0.2):
    return _frame([start + i * step for i in range(n)])


def test_weights_stay_within_bounds():
    w = _run(_steady())
    assert w.min() >= 0.0 and w.max() <= 1.0
    assert not w.isna().any()


def test_higher_volatility_gets_a_smaller_position():
    rng = np.random.default_rng(0)
    base = 100 + np.cumsum(rng.normal(0, 0.3, 400))
    choppy = _run(_frame(list(base), spread=6.0))
    quiet = _run(_frame(list(base), spread=0.5))
    # Same price path, wider true range -> smaller risk-budgeted weight.
    assert choppy.tail(50).mean() < quiet.tail(50).mean()


def test_a_wider_stop_multiple_reduces_size():
    tight = _run(_steady(), atr_mult=2.0)
    wide = _run(_steady(), atr_mult=6.0)
    assert wide.tail(50).mean() < tight.tail(50).mean()


def test_more_risk_budget_buys_a_bigger_position():
    small = _run(_steady(), risk_per_trade=0.01)
    large = _run(_steady(), risk_per_trade=0.04)
    assert large.tail(50).mean() > small.tail(50).mean()


def test_downtrend_dims_exposure_but_never_to_zero():
    down = _run(_frame([300 - i * 0.4 for i in range(400)]), bear_weight=0.4, dd_floor_weight=0.3)
    tail = down.tail(60)
    # A regime filter that flattens turns an unpredictable call into a binary
    # bet; this one only dims.
    assert tail.max() > 0.0
    up = _run(_steady())
    assert tail.mean() < up.tail(60).mean()


def test_drawdown_brake_cuts_size_as_price_falls_from_its_peak():
    path = [100 + i * 0.5 for i in range(200)] + [200 - i * 0.8 for i in range(200)]
    w = _run(_frame(path), max_drawdown=0.25, dd_floor_weight=0.2)
    assert w.iloc[-1] < w.iloc[190]      # deep in the drawdown vs near the peak


def test_runs_without_high_low_by_falling_back_to_close():
    frame = _steady()
    w = generate_atr_risk_budget(HOLD, {CODE: frame.drop(columns=["high", "low"])}, {})[CODE]
    assert not w.isna().any() and w.max() <= 1.0


def test_respects_the_holding_allocation_weight():
    half = [PaperHolding(symbol="X", market="us", allocation_pct=50.0)]
    full = generate_atr_risk_budget(HOLD, {CODE: _steady()}, {})[CODE]
    part = generate_atr_risk_budget(half, {CODE: _steady()}, {})[CODE]
    assert part.tail(50).mean() < full.tail(50).mean()


def test_smoothing_reduces_day_to_day_churn():
    rng = np.random.default_rng(1)
    base = 100 + np.cumsum(rng.normal(0, 1.2, 400))
    frame = _frame(list(base), spread=3.0)
    jumpy = _run(frame, smooth_window=1).diff().abs().mean()
    smooth = _run(frame, smooth_window=10).diff().abs().mean()
    assert smooth < jumpy
