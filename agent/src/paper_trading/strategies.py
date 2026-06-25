"""Strategy signal generators for paper trading backtests.

Each function returns ``Dict[str, pd.Series]`` — a signal map where values are
target portfolio weights in [0, 1].  The map is consumed by ``_align()`` and
``BaseEngine._execute_bars()`` from the existing backtest framework.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from src.paper_trading.models import PaperHolding


def _weight(holding: PaperHolding) -> float:
    return holding.allocation_pct / 100.0


# ── Buy & Hold ───────────────────────────────────────────────────────────────

def generate_buy_and_hold(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
) -> Dict[str, pd.Series]:
    """Constant weight across all dates."""
    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        dates = data_map[code].index
        signal_map[code] = pd.Series(_weight(h), index=dates)
    return signal_map


# ── Dollar-Cost Averaging ────────────────────────────────────────────────────

_FREQ_MAP = {
    "weekly": "W-MON",
    "biweekly": "2W-MON",
    "monthly": "MS",
}


def generate_dca(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Gradual weight ramp on a fixed schedule.

    On each DCA date the target weight steps up by ``step``, reaching the full
    allocation weight by the end of the period.  Between DCA dates the weight
    holds at its last value (no sell signal).
    """
    frequency = params.get("frequency", "monthly")
    freq = _FREQ_MAP.get(frequency, "MS")

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        dates = data_map[code].index
        if dates.empty:
            continue

        dca_dates = pd.date_range(start=dates[0], end=dates[-1], freq=freq)
        n_steps = max(len(dca_dates), 1)
        target_w = _weight(h)
        step = target_w / n_steps

        weights = pd.Series(0.0, index=dates)
        current_w = 0.0
        for dca_date in dca_dates:
            current_w = min(current_w + step, target_w)
            weights.loc[weights.index >= dca_date] = current_w

        signal_map[code] = weights
    return signal_map


# ── Grid Trading ─────────────────────────────────────────────────────────────

def generate_grid(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Price-level grid: buy at lower grids, sell at upper grids.

    The grid divides the price range [lower, upper] into ``grid_count`` equal
    bands.  The target weight is proportional to how far below the midpoint
    the price currently sits.  At the lower bound the weight equals the full
    allocation; at the upper bound the weight is zero (fully sold).
    """
    grid_count = max(int(params.get("grid_count", 5)), 2)
    auto_range = params.get("auto_range", True)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        df = data_map[code]
        if df.empty:
            continue

        close = df["close"]

        if auto_range:
            lower = float(close.min()) * 0.98
            upper = float(close.max()) * 1.02
        else:
            lower = float(params.get("lower_price", close.min()))
            upper = float(params.get("upper_price", close.max()))

        if upper <= lower:
            upper = lower * 1.1

        target_w = _weight(h)
        grid_levels = np.linspace(lower, upper, grid_count + 1)

        weights = pd.Series(0.0, index=close.index)
        for i, price in enumerate(close):
            bands_below = sum(1 for lvl in grid_levels if price <= lvl)
            ratio = bands_below / grid_count
            weights.iloc[i] = ratio * target_w

        signal_map[code] = weights
    return signal_map


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_code(holding: PaperHolding) -> str:
    """Build the internal code used by backtest loaders.

    US equities use ``AAPL.US`` format, HK equities use ``0700.HK``.
    The user may already supply suffixed symbols; normalise either way.
    """
    symbol = holding.symbol.strip().upper()
    if holding.market == "hk":
        digits = symbol.replace(".HK", "")
        return f"{int(digits):04d}.HK"
    return symbol if symbol.endswith(".US") else f"{symbol}.US"


def generate_signals(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    strategy_name: str,
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Dispatch to the appropriate strategy generator."""
    if strategy_name == "buy_and_hold":
        return generate_buy_and_hold(holdings, data_map)
    if strategy_name == "dca":
        return generate_dca(holdings, data_map, params)
    if strategy_name == "grid":
        return generate_grid(holdings, data_map, params)
    raise ValueError(f"Unknown strategy: {strategy_name}")
