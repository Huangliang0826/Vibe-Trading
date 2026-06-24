"""Naive forecast baselines — the honest comparators for any model.

Under the weak-form efficient-market hypothesis the best predictor of
tomorrow's price is today's price (random walk). These cheap baselines are
plotted alongside (and backtested against) TimesFM so the user can see whether
the foundation model actually adds anything. Usually it barely does.
"""
from __future__ import annotations

import numpy as np


def random_walk(closes: list[float], horizon: int) -> list[float]:
    """Flat: carry the last observed close forward (the canonical naive forecast)."""
    last = float(closes[-1])
    return [last] * horizon


def drift(closes: list[float], horizon: int, lookback: int = 63) -> list[float]:
    """Linear drift: extrapolate the average per-step change over ``lookback`` days.

    ``lookback`` defaults to ~3 months of trading days. This is the "trend
    continuation" strawman — it looks compelling in a trending market and
    fails hard at turning points.
    """
    arr = np.asarray(closes, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return [float(arr[-1])] * horizon if arr.size else [0.0] * horizon
    window = arr[-lookback:] if arr.size > lookback else arr
    avg_step = (window[-1] - window[0]) / max(len(window) - 1, 1)
    last = float(arr[-1])
    return [last + avg_step * (i + 1) for i in range(horizon)]
