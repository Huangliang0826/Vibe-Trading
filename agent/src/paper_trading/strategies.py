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


# ── Momentum Breakout ────────────────────────────────────────────────────────

def generate_momentum_breakout(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Buy strength after a breakout, exit when trend weakens."""
    lookback = max(int(params.get("lookback", 20)), 5)
    exit_ma = max(int(params.get("exit_ma", 20)), 5)
    stop_loss = float(params.get("stop_loss", 0.08))

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue

        rolling_high = close.shift(1).rolling(lookback, min_periods=max(3, lookback // 2)).max()
        trend_ma = close.rolling(exit_ma, min_periods=max(3, exit_ma // 2)).mean()
        target_w = _weight(h)
        weights = pd.Series(0.0, index=close.index)
        in_position = False
        entry_price = 0.0

        for i, price in enumerate(close):
            if not in_position and pd.notna(rolling_high.iloc[i]) and price > rolling_high.iloc[i]:
                in_position = True
                entry_price = float(price)
            elif in_position:
                hit_stop = entry_price > 0 and price <= entry_price * (1 - stop_loss)
                lost_trend = pd.notna(trend_ma.iloc[i]) and price < trend_ma.iloc[i]
                if hit_stop or lost_trend:
                    in_position = False
                    entry_price = 0.0
            weights.iloc[i] = target_w if in_position else 0.0

        signal_map[code] = weights
    return signal_map


# ── Moving Average Cross ─────────────────────────────────────────────────────

def generate_moving_average_cross(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Hold while the fast moving average is above the slow moving average."""
    short_window = max(int(params.get("short_window", 20)), 2)
    long_window = max(int(params.get("long_window", 60)), short_window + 1)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue
        fast = close.rolling(short_window, min_periods=max(2, short_window // 2)).mean()
        slow = close.rolling(long_window, min_periods=max(3, long_window // 2)).mean()
        signal_map[code] = ((fast > slow).astype(float) * _weight(h)).reindex(close.index).fillna(0.0)
    return signal_map


# ── RSI Reversion ────────────────────────────────────────────────────────────

def generate_rsi_reversion(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Buy oversold weakness and exit after overbought rebounds."""
    window = max(int(params.get("window", 14)), 2)
    buy_below = float(params.get("buy_below", 35))
    sell_above = float(params.get("sell_above", 65))

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue
        rsi = _rsi(close, window)
        weights = pd.Series(0.0, index=close.index)
        in_position = False
        for i, value in enumerate(rsi):
            if not in_position and pd.notna(value) and value <= buy_below:
                in_position = True
            elif in_position and pd.notna(value) and value >= sell_above:
                in_position = False
            weights.iloc[i] = _weight(h) if in_position else 0.0
        signal_map[code] = weights
    return signal_map


# ── Volatility Target ────────────────────────────────────────────────────────

def generate_volatility_target(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Scale exposure down when realised volatility rises."""
    window = max(int(params.get("window", 20)), 5)
    target_vol = max(float(params.get("target_vol", 0.18)), 0.01)
    min_weight_ratio = max(float(params.get("min_weight_ratio", 0.15)), 0.0)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue
        realised_vol = close.pct_change().rolling(window, min_periods=max(3, window // 2)).std() * np.sqrt(252)
        ratio = (target_vol / realised_vol.replace(0, np.nan)).clip(lower=min_weight_ratio, upper=1.0)
        signal_map[code] = (ratio.fillna(min_weight_ratio) * _weight(h)).reindex(close.index).fillna(0.0)
    return signal_map


# ── Drawdown Rebalance ──────────────────────────────────────────────────────

def generate_drawdown_rebalance(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Add exposure in drawdowns, trim after recovery toward prior highs."""
    first_level = float(params.get("first_level", 0.05))
    second_level = float(params.get("second_level", 0.10))
    third_level = float(params.get("third_level", 0.15))
    recovery_trim = float(params.get("recovery_trim", 0.03))

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue
        peak = close.cummax().replace(0, np.nan)
        drawdown = (close / peak - 1).fillna(0.0)
        target_w = _weight(h)
        weights = pd.Series(0.0, index=close.index)

        for i, dd in enumerate(drawdown):
            loss = abs(min(float(dd), 0.0))
            if loss >= third_level:
                ratio = 1.0
            elif loss >= second_level:
                ratio = 0.75
            elif loss >= first_level:
                ratio = 0.5
            else:
                ratio = 0.25

            near_high = loss <= recovery_trim
            if near_high:
                ratio = min(ratio, 0.25)
            weights.iloc[i] = ratio * target_w

        signal_map[code] = weights
    return signal_map


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window, min_periods=max(2, window // 2)).mean()
    loss = (-delta.clip(upper=0)).rolling(window, min_periods=max(2, window // 2)).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50.0)


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
    if strategy_name == "momentum_breakout":
        return generate_momentum_breakout(holdings, data_map, params)
    if strategy_name == "moving_average_cross":
        return generate_moving_average_cross(holdings, data_map, params)
    if strategy_name == "rsi_reversion":
        return generate_rsi_reversion(holdings, data_map, params)
    if strategy_name == "volatility_target":
        return generate_volatility_target(holdings, data_map, params)
    if strategy_name == "drawdown_rebalance":
        return generate_drawdown_rebalance(holdings, data_map, params)
    raise ValueError(f"Unknown strategy: {strategy_name}")
