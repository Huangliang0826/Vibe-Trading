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
    allocation weight after ``steps_to_full`` periods.  Between DCA dates the
    weight holds at its last value (no sell signal).
    """
    frequency = params.get("frequency", "monthly")
    freq = _FREQ_MAP.get(frequency, "MS")
    steps_to_full = max(int(params.get("steps_to_full", 12)), 1)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        dates = data_map[code].index
        if dates.empty:
            continue

        dca_dates = pd.date_range(start=dates[0], end=dates[-1], freq=freq)
        target_w = _weight(h)
        step = target_w / steps_to_full

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
    """Price-level grid using only information available at each date.

    Auto range uses a rolling historical low/high shifted by one bar, avoiding
    future leakage. Exposure is stepped into ``grid_count`` bands: near the
    lower bound the strategy approaches the full allocation, and near the upper
    bound it approaches cash.
    """
    grid_count = max(int(params.get("grid_count", 5)), 2)
    auto_range = params.get("auto_range", True)
    range_lookback = max(int(params.get("range_lookback", 120)), grid_count * 2)
    range_buffer = max(float(params.get("range_buffer", 0.02)), 0.0)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        df = data_map[code]
        if df.empty:
            continue

        close = df["close"].astype(float)

        has_manual_bounds = params.get("lower_price") is not None and params.get("upper_price") is not None

        if auto_range or not has_manual_bounds:
            past_close = close.shift(1)
            min_periods = max(3, min(range_lookback // 3, range_lookback))
            rolling_low = past_close.rolling(range_lookback, min_periods=min_periods).min()
            rolling_high = past_close.rolling(range_lookback, min_periods=min_periods).max()
            expanding_low = past_close.expanding(min_periods=1).min()
            expanding_high = past_close.expanding(min_periods=1).max()
            lower_series = rolling_low.combine_first(expanding_low).fillna(close.iloc[0]) * (1 - range_buffer)
            upper_series = rolling_high.combine_first(expanding_high).fillna(close.iloc[0]) * (1 + range_buffer)
        else:
            lower = float(params["lower_price"])
            upper = float(params["upper_price"])
            if upper <= lower:
                upper = lower * 1.1
            lower_series = pd.Series(lower, index=close.index)
            upper_series = pd.Series(upper, index=close.index)

        target_w = _weight(h)

        weights = pd.Series(0.0, index=close.index)
        for i, price in enumerate(close):
            lower = float(lower_series.iloc[i])
            upper = float(upper_series.iloc[i])
            if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
                weights.iloc[i] = weights.iloc[i - 1] if i > 0 else target_w * 0.5
                continue
            raw_ratio = (upper - float(price)) / (upper - lower)
            ratio = float(np.clip(raw_ratio, 0.0, 1.0))
            stepped_ratio = np.floor(ratio * grid_count + 0.5) / grid_count
            weights.iloc[i] = float(np.clip(stepped_ratio * target_w, 0.0, target_w))

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


# ── Trend + Volatility Filter ────────────────────────────────────────────────

def generate_trend_volatility_filter(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Hold only in an uptrend, then scale exposure by realised volatility."""
    ma_window = max(int(params.get("ma_window", 120)), 10)
    vol_window = max(int(params.get("vol_window", 20)), 5)
    target_vol = max(float(params.get("target_vol", 0.18)), 0.01)
    min_weight_ratio = max(float(params.get("min_weight_ratio", 0.10)), 0.0)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue
        trend_ma = close.rolling(ma_window, min_periods=max(5, ma_window // 3)).mean()
        realised_vol = close.pct_change().rolling(vol_window, min_periods=max(3, vol_window // 2)).std() * np.sqrt(252)
        vol_ratio = (target_vol / realised_vol.replace(0, np.nan)).clip(lower=min_weight_ratio, upper=1.0)
        in_trend = close > trend_ma
        weights = (in_trend.astype(float) * vol_ratio.fillna(min_weight_ratio) * _weight(h))
        signal_map[code] = weights.reindex(close.index).fillna(0.0)
    return signal_map


# ── Donchian Breakout ────────────────────────────────────────────────────────

def generate_donchian_breakout(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Buy new highs and exit when price breaks below a recent low."""
    entry_window = max(int(params.get("entry_window", 55)), 5)
    exit_window = max(int(params.get("exit_window", 20)), 3)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue
        entry_high = close.shift(1).rolling(entry_window, min_periods=max(3, entry_window // 3)).max()
        exit_low = close.shift(1).rolling(exit_window, min_periods=max(3, exit_window // 3)).min()
        weights = pd.Series(0.0, index=close.index)
        in_position = False
        for i, price in enumerate(close):
            if not in_position and pd.notna(entry_high.iloc[i]) and price > entry_high.iloc[i]:
                in_position = True
            elif in_position and pd.notna(exit_low.iloc[i]) and price < exit_low.iloc[i]:
                in_position = False
            weights.iloc[i] = _weight(h) if in_position else 0.0
        signal_map[code] = weights
    return signal_map


# ── Bollinger Reversion ──────────────────────────────────────────────────────

def generate_bollinger_reversion(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Buy below the lower band and sell after mean reversion."""
    window = max(int(params.get("window", 20)), 5)
    band_width = max(float(params.get("band_width", 2.0)), 0.5)
    exit_at = params.get("exit_at", "middle")

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue
        middle = close.rolling(window, min_periods=max(3, window // 2)).mean()
        std = close.rolling(window, min_periods=max(3, window // 2)).std()
        lower = middle - band_width * std
        upper = middle + band_width * std
        weights = pd.Series(0.0, index=close.index)
        in_position = False
        for i, price in enumerate(close):
            if not in_position and pd.notna(lower.iloc[i]) and price < lower.iloc[i]:
                in_position = True
            elif in_position:
                exit_level = upper.iloc[i] if exit_at == "upper" else middle.iloc[i]
                if pd.notna(exit_level) and price >= exit_level:
                    in_position = False
            weights.iloc[i] = _weight(h) if in_position else 0.0
        signal_map[code] = weights
    return signal_map


# ── Trailing Stop ────────────────────────────────────────────────────────────

def generate_trailing_stop(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Enter on trend confirmation and protect gains with a trailing stop."""
    ma_window = max(int(params.get("ma_window", 60)), 5)
    trailing_stop = float(params.get("trailing_stop", 0.12))
    reentry_buffer = float(params.get("reentry_buffer", 0.02))

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue
        trend_ma = close.rolling(ma_window, min_periods=max(5, ma_window // 3)).mean()
        weights = pd.Series(0.0, index=close.index)
        in_position = False
        high_water = 0.0
        for i, price in enumerate(close):
            ma = trend_ma.iloc[i]
            if not in_position and pd.notna(ma) and price > ma * (1 + reentry_buffer):
                in_position = True
                high_water = float(price)
            elif in_position:
                high_water = max(high_water, float(price))
                hit_stop = high_water > 0 and price <= high_water * (1 - trailing_stop)
                lost_trend = pd.notna(ma) and price < ma
                if hit_stop or lost_trend:
                    in_position = False
                    high_water = 0.0
            weights.iloc[i] = _weight(h) if in_position else 0.0
        signal_map[code] = weights
    return signal_map


# ── Monthly Rebalance ────────────────────────────────────────────────────────

def generate_monthly_rebalance(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Rebalance back to target allocation on the first trading day each month."""
    initial_cash_ratio = max(float(params.get("initial_cash_ratio", 0.0)), 0.0)
    active_ratio = max(1.0 - initial_cash_ratio, 0.0)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        dates = data_map[code].index
        if dates.empty:
            continue
        weights = pd.Series(_weight(h) * active_ratio, index=dates)
        month_start = pd.Series(dates.to_period("M"), index=dates).ne(pd.Series(dates.to_period("M"), index=dates).shift(1))
        weights.loc[~month_start] = np.nan
        signal_map[code] = weights.ffill().fillna(_weight(h) * active_ratio)
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
    if strategy_name == "trend_volatility_filter":
        return generate_trend_volatility_filter(holdings, data_map, params)
    if strategy_name == "donchian_breakout":
        return generate_donchian_breakout(holdings, data_map, params)
    if strategy_name == "bollinger_reversion":
        return generate_bollinger_reversion(holdings, data_map, params)
    if strategy_name == "trailing_stop":
        return generate_trailing_stop(holdings, data_map, params)
    if strategy_name == "monthly_rebalance":
        return generate_monthly_rebalance(holdings, data_map, params)
    raise ValueError(f"Unknown strategy: {strategy_name}")
