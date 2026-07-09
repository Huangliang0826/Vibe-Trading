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


# ── 200-day SMA timing (Faber's 10-month timing on daily bars) ──────────────

def generate_ma200_timing(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Hold while the close sits above its long SMA, go to cash below it.

    Meb Faber's classic timing rule (10-month SMA ≈ 200 trading days): fully
    invested when close > SMA, fully in cash otherwise. No position scaling,
    no second indicator — the entire edge is sidestepping deep bear legs.
    Until the SMA has a full window of history the signal stays in cash.
    """
    window = max(int(params.get("window", 200)), 20)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue
        sma = close.rolling(window, min_periods=window).mean()
        signal_map[code] = ((close > sma).astype(float) * _weight(h)).reindex(close.index).fillna(0.0)
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


# ── ATR Trend Stop ───────────────────────────────────────────────────────────

def generate_atr_trend_stop(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Trend-following entry with an ATR-based protective stop.

    Enter when price is above a trend MA and makes a recent high.  While in the
    trade, trail a stop at ``highest_close - atr_multiple * ATR`` and exit when
    price closes below it or loses the trend MA.
    """
    ma_window = max(int(params.get("ma_window", 80)), 10)
    breakout_window = max(int(params.get("breakout_window", 20)), 5)
    atr_window = max(int(params.get("atr_window", 14)), 3)
    atr_multiple = max(float(params.get("atr_multiple", 3.0)), 0.5)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        df = data_map[code]
        if df.empty:
            continue

        close = df["close"].astype(float)
        high = df.get("high", close).astype(float)
        low = df.get("low", close).astype(float)
        trend_ma = close.rolling(ma_window, min_periods=max(5, ma_window // 3)).mean()
        prior_high = close.shift(1).rolling(
            breakout_window, min_periods=max(3, breakout_window // 2)
        ).max()
        atr = _atr(high, low, close, atr_window)

        target_w = _weight(h)
        weights = pd.Series(0.0, index=close.index)
        in_position = False
        highest_close = 0.0

        for i, price in enumerate(close):
            ma = trend_ma.iloc[i]
            breakout_level = prior_high.iloc[i]
            current_atr = atr.iloc[i]

            if not in_position:
                if (
                    pd.notna(ma)
                    and pd.notna(breakout_level)
                    and price > ma
                    and price > breakout_level
                ):
                    in_position = True
                    highest_close = float(price)
            else:
                highest_close = max(highest_close, float(price))
                stop_level = highest_close - atr_multiple * float(current_atr) if pd.notna(current_atr) else -np.inf
                hit_stop = price < stop_level
                lost_trend = pd.notna(ma) and price < ma
                if hit_stop or lost_trend:
                    in_position = False
                    highest_close = 0.0

            weights.iloc[i] = target_w if in_position else 0.0

        signal_map[code] = weights
    return signal_map


# ── Mean Reversion Scale-Out ─────────────────────────────────────────────────

def generate_mean_reversion_scaleout(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Buy oversold weakness and scale out as price mean-reverts."""
    window = max(int(params.get("window", 20)), 5)
    band_width = max(float(params.get("band_width", 2.0)), 0.5)
    stop_loss = max(float(params.get("stop_loss", 0.12)), 0.01)

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

        target_w = _weight(h)
        weights = pd.Series(0.0, index=close.index)
        position_ratio = 0.0
        entry_price = 0.0

        for i, price in enumerate(close):
            mid = middle.iloc[i]
            low_band = lower.iloc[i]
            high_band = upper.iloc[i]

            if position_ratio <= 0:
                if pd.notna(low_band) and price <= low_band:
                    position_ratio = 1.0
                    entry_price = float(price)
            else:
                if entry_price > 0 and price <= entry_price * (1 - stop_loss):
                    position_ratio = 0.0
                    entry_price = 0.0
                elif pd.notna(high_band) and price >= high_band:
                    position_ratio = 0.0
                    entry_price = 0.0
                elif pd.notna(mid) and price >= mid:
                    position_ratio = min(position_ratio, 0.5)

            weights.iloc[i] = target_w * position_ratio

        signal_map[code] = weights
    return signal_map


# ── Enhanced DCA + Trend Filter ──────────────────────────────────────────────

def generate_enhanced_dca_trend(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Ramp exposure on a DCA schedule, then reduce risk in weak trends."""
    frequency = params.get("frequency", "monthly")
    freq = _FREQ_MAP.get(frequency, "MS")
    steps_to_full = max(int(params.get("steps_to_full", 12)), 1)
    ma_window = max(int(params.get("ma_window", 120)), 10)
    min_ratio = float(np.clip(float(params.get("min_ratio", 0.25)), 0.0, 1.0))
    boost_ratio = max(float(params.get("boost_ratio", 1.25)), 1.0)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue

        target_w = _weight(h)
        base = pd.Series(0.0, index=close.index)
        dca_dates = pd.date_range(start=close.index[0], end=close.index[-1], freq=freq)
        current_w = 0.0
        step = target_w / steps_to_full
        for dca_date in dca_dates:
            current_w = min(current_w + step, target_w)
            base.loc[base.index >= dca_date] = current_w

        ma = close.rolling(ma_window, min_periods=max(5, ma_window // 3)).mean()
        distance = close / ma.replace(0, np.nan) - 1.0
        trend_up = close > ma
        ratio = pd.Series(1.0, index=close.index)
        ratio.loc[~trend_up.fillna(False)] = min_ratio
        ratio.loc[(trend_up.fillna(False)) & (distance <= -0.08)] = boost_ratio
        signal_map[code] = (base * ratio).clip(lower=0.0, upper=target_w).fillna(0.0)
    return signal_map


# ── Breakout Pullback ────────────────────────────────────────────────────────

def generate_breakout_pullback(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Wait for a breakout, then buy the first controlled pullback."""
    breakout_window = max(int(params.get("breakout_window", 50)), 10)
    confirm_window = max(int(params.get("confirm_window", 10)), 3)
    pullback_pct = max(float(params.get("pullback_pct", 0.05)), 0.005)
    stop_loss = max(float(params.get("stop_loss", 0.10)), 0.01)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue

        prior_high = close.shift(1).rolling(
            breakout_window, min_periods=max(5, breakout_window // 3)
        ).max()
        support = close.shift(1).rolling(
            confirm_window, min_periods=max(3, confirm_window // 2)
        ).min()
        target_w = _weight(h)
        weights = pd.Series(0.0, index=close.index)
        breakout_level = 0.0
        waiting_pullback = False
        in_position = False
        entry_price = 0.0

        for i, price in enumerate(close):
            high_level = prior_high.iloc[i]
            support_level = support.iloc[i]

            if not in_position:
                if not waiting_pullback and pd.notna(high_level) and price > high_level:
                    waiting_pullback = True
                    breakout_level = float(high_level)
                elif waiting_pullback:
                    near_breakout = breakout_level > 0 and price <= breakout_level * (1 + pullback_pct)
                    holds_support = pd.notna(support_level) and price >= support_level
                    if near_breakout and holds_support:
                        in_position = True
                        waiting_pullback = False
                        entry_price = float(price)
                    elif breakout_level > 0 and price < breakout_level * (1 - stop_loss):
                        waiting_pullback = False
                        breakout_level = 0.0
            else:
                hit_stop = entry_price > 0 and price <= entry_price * (1 - stop_loss)
                lost_support = pd.notna(support_level) and price < support_level
                if hit_stop or lost_support:
                    in_position = False
                    entry_price = 0.0
                    breakout_level = 0.0

            weights.iloc[i] = target_w if in_position else 0.0

        signal_map[code] = weights
    return signal_map


# ── Quality Momentum ─────────────────────────────────────────────────────────

def generate_quality_momentum(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Rank by return quality: momentum minus volatility and drawdown penalty."""
    lookback = max(int(params.get("lookback", 120)), 20)
    top_n = max(int(params.get("top_n", 1)), 1)
    vol_penalty = max(float(params.get("vol_penalty", 0.6)), 0.0)
    dd_penalty = max(float(params.get("dd_penalty", 0.8)), 0.0)

    codes = [_to_code(h) for h in holdings if _to_code(h) in data_map]
    if not codes:
        return {}
    total_budget = min(sum(_weight(h) for h in holdings if _to_code(h) in data_map), 1.0)
    trading_idx = pd.DatetimeIndex(sorted(set().union(*(data_map[c].index for c in codes))))
    months = pd.Series(trading_idx.to_period("M"), index=trading_idx)
    is_rebalance = months.ne(months.shift(1))
    weights = {c: pd.Series(0.0, index=trading_idx) for c in codes}
    current = {c: 0.0 for c in codes}

    close_map = {c: data_map[c]["close"].astype(float).reindex(trading_idx).ffill() for c in codes}
    for ts in trading_idx:
        if bool(is_rebalance.loc[ts]):
            scored: list[tuple[str, float]] = []
            for c in codes:
                history = close_map[c].loc[:ts].tail(lookback + 1)
                if len(history) < max(20, lookback // 3):
                    continue
                ret = float(history.iloc[-1] / history.iloc[0] - 1.0)
                daily = history.pct_change().dropna()
                vol = float(daily.std() * np.sqrt(252)) if not daily.empty else 0.0
                peak = history.cummax().replace(0, np.nan)
                max_dd = abs(float((history / peak - 1.0).min()))
                score = ret - vol_penalty * vol - dd_penalty * max_dd
                if ret > 0:
                    scored.append((c, score))
            scored.sort(key=lambda x: x[1], reverse=True)
            winners = [c for c, _ in scored[:top_n]]
            current = {c: 0.0 for c in codes}
            if winners:
                per = total_budget / len(winners)
                for c in winners:
                    current[c] = per
        for c in codes:
            weights[c].loc[ts] = current[c]
    return weights


# ── Low Volatility Defensive Rotation ────────────────────────────────────────

def generate_low_volatility_rotation(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Hold the lowest-volatility asset whose trend is not broken."""
    window = max(int(params.get("window", 60)), 10)
    trend_window = max(int(params.get("trend_window", 120)), 20)
    top_n = max(int(params.get("top_n", 1)), 1)

    codes = [_to_code(h) for h in holdings if _to_code(h) in data_map]
    if not codes:
        return {}
    total_budget = min(sum(_weight(h) for h in holdings if _to_code(h) in data_map), 1.0)
    trading_idx = pd.DatetimeIndex(sorted(set().union(*(data_map[c].index for c in codes))))
    months = pd.Series(trading_idx.to_period("M"), index=trading_idx)
    is_rebalance = months.ne(months.shift(1))
    close_map = {c: data_map[c]["close"].astype(float).reindex(trading_idx).ffill() for c in codes}
    weights = {c: pd.Series(0.0, index=trading_idx) for c in codes}
    current = {c: 0.0 for c in codes}

    for ts in trading_idx:
        if bool(is_rebalance.loc[ts]):
            scored: list[tuple[str, float]] = []
            for c in codes:
                close = close_map[c].loc[:ts]
                if len(close) < max(20, window // 2):
                    continue
                vol = close.pct_change().tail(window).std()
                ma = close.tail(trend_window).mean()
                if pd.isna(vol) or pd.isna(ma) or close.iloc[-1] < ma:
                    continue
                scored.append((c, float(vol)))
            scored.sort(key=lambda x: x[1])
            winners = [c for c, _ in scored[:top_n]]
            current = {c: 0.0 for c in codes}
            if winners:
                per = total_budget / len(winners)
                for c in winners:
                    current[c] = per
        for c in codes:
            weights[c].loc[ts] = current[c]
    return weights


# ── Volatility Squeeze Breakout ──────────────────────────────────────────────

def generate_volatility_squeeze_breakout(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Buy only after volatility compression resolves into an upside breakout."""
    window = max(int(params.get("window", 20)), 5)
    squeeze_window = max(int(params.get("squeeze_window", 120)), window * 2)
    breakout_window = max(int(params.get("breakout_window", 20)), 5)
    width_quantile = float(np.clip(float(params.get("width_quantile", 0.25)), 0.05, 0.8))
    stop_loss = max(float(params.get("stop_loss", 0.10)), 0.01)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        df = data_map[code]
        if df.empty:
            continue
        close = df["close"].astype(float)
        volume = df.get("volume", pd.Series(1.0, index=close.index)).astype(float)
        middle = close.rolling(window, min_periods=max(3, window // 2)).mean()
        std = close.rolling(window, min_periods=max(3, window // 2)).std()
        band_width = (4 * std / middle.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        squeeze_threshold = band_width.shift(1).rolling(
            squeeze_window, min_periods=max(20, squeeze_window // 4)
        ).quantile(width_quantile)
        prior_high = close.shift(1).rolling(
            breakout_window, min_periods=max(3, breakout_window // 2)
        ).max()
        vol_ma = volume.shift(1).rolling(window, min_periods=max(3, window // 2)).mean()

        target_w = _weight(h)
        weights = pd.Series(0.0, index=close.index)
        in_position = False
        entry_price = 0.0
        for i, price in enumerate(close):
            squeezed = pd.notna(squeeze_threshold.iloc[i]) and band_width.iloc[i] <= squeeze_threshold.iloc[i]
            breakout = pd.notna(prior_high.iloc[i]) and price > prior_high.iloc[i]
            volume_confirm = pd.isna(vol_ma.iloc[i]) or volume.iloc[i] >= vol_ma.iloc[i]
            if not in_position and squeezed and breakout and volume_confirm:
                in_position = True
                entry_price = float(price)
            elif in_position:
                hit_stop = entry_price > 0 and price <= entry_price * (1 - stop_loss)
                lost_middle = pd.notna(middle.iloc[i]) and price < middle.iloc[i]
                if hit_stop or lost_middle:
                    in_position = False
                    entry_price = 0.0
            weights.iloc[i] = target_w if in_position else 0.0
        signal_map[code] = weights
    return signal_map


# ── Risk Parity ──────────────────────────────────────────────────────────────

def generate_risk_parity(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Allocate the portfolio budget inversely to each asset's recent volatility."""
    window = max(int(params.get("window", 60)), 5)
    rebalance = params.get("rebalance", "monthly")

    codes = [_to_code(h) for h in holdings if _to_code(h) in data_map]
    if not codes:
        return {}
    total_budget = min(sum(_weight(h) for h in holdings if _to_code(h) in data_map), 1.0)
    trading_idx = pd.DatetimeIndex(sorted(set().union(*(data_map[c].index for c in codes))))
    if rebalance == "weekly":
        periods = pd.Series(trading_idx.to_period("W"), index=trading_idx)
    else:
        periods = pd.Series(trading_idx.to_period("M"), index=trading_idx)
    is_rebalance = periods.ne(periods.shift(1))
    close_map = {c: data_map[c]["close"].astype(float).reindex(trading_idx).ffill() for c in codes}
    weights = {c: pd.Series(0.0, index=trading_idx) for c in codes}
    current = {c: total_budget / len(codes) for c in codes}

    for ts in trading_idx:
        if bool(is_rebalance.loc[ts]):
            inv_vol: dict[str, float] = {}
            for c in codes:
                returns = close_map[c].loc[:ts].pct_change().tail(window).dropna()
                vol = float(returns.std()) if not returns.empty else np.nan
                inv_vol[c] = 1.0 / max(vol, 1e-6) if np.isfinite(vol) else 0.0
            denom = sum(inv_vol.values())
            if denom > 0:
                current = {c: total_budget * inv_vol[c] / denom for c in codes}
        for c in codes:
            weights[c].loc[ts] = current[c]
    return weights


# ── Price / Volume Efficiency Rotation ───────────────────────────────────────

def generate_price_volume_efficiency(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Cross-sectional rotation using split upside/downside price-volume efficiency.

    Score components:
    - high upside efficiency is good;
    - high downside efficiency is bad;
    - volume confirmation on efficient upside is good;
    - volume confirmation on efficient downside is bad.
    """
    lookback = max(int(params.get("lookback", 60)), 8)
    top_n = max(int(params.get("top_n", 3)), 1)
    rebalance = params.get("rebalance", "monthly")

    codes = [_to_code(h) for h in holdings if _to_code(h) in data_map]
    if not codes:
        return {}
    total_budget = min(sum(_weight(h) for h in holdings if _to_code(h) in data_map), 1.0)
    trading_idx = pd.DatetimeIndex(sorted(set().union(*(data_map[c].index for c in codes))))
    if rebalance == "weekly":
        periods = pd.Series(trading_idx.to_period("W"), index=trading_idx)
    else:
        periods = pd.Series(trading_idx.to_period("M"), index=trading_idx)
    is_rebalance = periods.ne(periods.shift(1))
    close_map = {c: data_map[c]["close"].astype(float).reindex(trading_idx).ffill() for c in codes}
    volume_map = {
        c: data_map[c].get("volume", pd.Series(1.0, index=data_map[c].index)).astype(float).reindex(trading_idx).ffill()
        for c in codes
    }
    weights = {c: pd.Series(0.0, index=trading_idx) for c in codes}
    current = {c: 0.0 for c in codes}

    for ts in trading_idx:
        if bool(is_rebalance.loc[ts]):
            features: dict[str, dict[str, float]] = {}
            for c in codes:
                close = close_map[c].loc[:ts].tail(lookback + 1)
                volume = volume_map[c].loc[:ts].tail(lookback + 1)
                if len(close) < max(8, lookback // 3):
                    continue
                ret = close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
                if ret.empty:
                    continue
                log_vol_change = np.log(volume.replace(0, np.nan)).diff().reindex(ret.index).replace([np.inf, -np.inf], np.nan)
                up = ret.clip(lower=0)
                down = (-ret.clip(upper=0))
                up_sum = float(up.sum())
                down_sum = float(down.sum())
                up_eff = up_sum / (float(up.std()) * np.sqrt(len(up)) + 1e-6)
                down_eff = down_sum / (float(down.std()) * np.sqrt(len(down)) + 1e-6)
                up_corr = _safe_corr(up, log_vol_change)
                down_corr = _safe_corr(down, log_vol_change)
                total_ret = float(close.iloc[-1] / close.iloc[0] - 1.0)
                if total_ret <= 0 and len(codes) > top_n:
                    continue
                features[c] = {
                    "up_eff": up_eff,
                    "down_eff": down_eff,
                    "up_confirm": up_eff * max(up_corr, 0.0),
                    "down_risk": down_eff * max(down_corr, 0.0),
                }

            scores: dict[str, float] = {}
            if features:
                up_rank = _rank_feature(features, "up_eff", ascending=True)
                down_rank = _rank_feature(features, "down_eff", ascending=False)
                up_confirm_rank = _rank_feature(features, "up_confirm", ascending=True)
                down_risk_rank = _rank_feature(features, "down_risk", ascending=False)
                for c in features:
                    scores[c] = (
                        0.35 * up_rank[c]
                        + 0.25 * down_rank[c]
                        + 0.25 * up_confirm_rank[c]
                        + 0.15 * down_risk_rank[c]
                    )

            winners = [c for c, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]]
            current = {c: 0.0 for c in codes}
            if winners:
                per = total_budget / len(winners)
                for c in winners:
                    current[c] = per
        for c in codes:
            weights[c].loc[ts] = current[c]
    return weights


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


# ── MACD Divergence ──────────────────────────────────────────────────────────

def generate_macd_divergence(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Enter on bullish MACD divergence, exit on bearish divergence / cross-down.

    A bullish divergence is when price prints a lower low over the lookback but
    the MACD line prints a higher low — momentum is fading on the downside.  We
    confirm with the histogram turning up before buying, and exit when the MACD
    crosses below its signal line or a bearish divergence appears.  All inputs
    use only past bars, so there is no look-ahead.
    """
    fast = max(int(params.get("fast", 12)), 2)
    slow = max(int(params.get("slow", 26)), fast + 1)
    signal_window = max(int(params.get("signal", 9)), 2)
    lookback = max(int(params.get("lookback", 20)), 5)

    signal_map: Dict[str, pd.Series] = {}
    for h in holdings:
        code = _to_code(h)
        if code not in data_map:
            continue
        close = data_map[code]["close"].astype(float)
        if close.empty:
            continue

        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal_window, adjust=False).mean()
        hist = macd - macd_signal

        prev_close = close.shift(lookback)
        prev_macd = macd.shift(lookback)
        prev_hist = hist.shift(1)

        target_w = _weight(h)
        weights = pd.Series(0.0, index=close.index)
        in_position = False

        for i in range(len(close)):
            price = float(close.iloc[i])
            if i < lookback or pd.isna(prev_close.iloc[i]) or pd.isna(prev_macd.iloc[i]):
                weights.iloc[i] = target_w if in_position else 0.0
                continue

            lower_low = price < float(prev_close.iloc[i])
            macd_higher = float(macd.iloc[i]) > float(prev_macd.iloc[i])
            hist_turning_up = pd.notna(prev_hist.iloc[i]) and float(hist.iloc[i]) > float(prev_hist.iloc[i])

            higher_high = price > float(prev_close.iloc[i])
            macd_lower = float(macd.iloc[i]) < float(prev_macd.iloc[i])
            cross_down = float(macd.iloc[i]) < float(macd_signal.iloc[i])

            if not in_position:
                if lower_low and macd_higher and hist_turning_up:
                    in_position = True
            else:
                bearish_div = higher_high and macd_lower
                if bearish_div or cross_down:
                    in_position = False

            weights.iloc[i] = target_w if in_position else 0.0

        signal_map[code] = weights
    return signal_map


# ── Dual Momentum ────────────────────────────────────────────────────────────

def generate_dual_momentum(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Antonacci dual momentum across the portfolio's holdings.

    On each monthly rebalance we rank holdings by their trailing ``lookback``
    return (relative momentum) and hold only the ``top_n`` whose return is also
    positive (absolute momentum) — the rest goes to cash.  The selected winners
    split the portfolio's total budget equally and are held until the next
    rebalance.  Returns are measured on past closes only, so no look-ahead.
    """
    lookback = max(int(params.get("lookback", 120)), 20)
    top_n = max(int(params.get("top_n", 1)), 1)

    codes = [_to_code(h) for h in holdings if _to_code(h) in data_map]
    if not codes:
        return {}

    total_budget = sum(_weight(h) for h in holdings if _to_code(h) in data_map)
    total_budget = min(total_budget, 1.0)

    all_dates = sorted(set().union(*(data_map[c].index for c in codes)))
    trading_idx = pd.DatetimeIndex(all_dates)

    # Trailing return per code on the shared calendar (past data only).
    mom: Dict[str, pd.Series] = {}
    for c in codes:
        close = data_map[c]["close"].astype(float).reindex(trading_idx).ffill()
        mom[c] = close / close.shift(lookback) - 1.0

    # Rebalance on the first trading day of each month.
    months = pd.Series(trading_idx.to_period("M"), index=trading_idx)
    is_rebalance = months.ne(months.shift(1))

    weights = {c: pd.Series(0.0, index=trading_idx) for c in codes}
    current: Dict[str, float] = {c: 0.0 for c in codes}

    for ts in trading_idx:
        if bool(is_rebalance.loc[ts]):
            scored = [
                (c, float(mom[c].loc[ts]))
                for c in codes
                if pd.notna(mom[c].loc[ts]) and float(mom[c].loc[ts]) > 0
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            winners = [c for c, _ in scored[:top_n]]
            current = {c: 0.0 for c in codes}
            if winners:
                per = total_budget / len(winners)
                for c in winners:
                    current[c] = per
        for c in codes:
            weights[c].loc[ts] = current[c]

    return {c: weights[c] for c in codes}


# ── Volatility + Trend Rotation (risk-on / risk-off) ─────────────────────────

def generate_vol_trend_rotation(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> Dict[str, pd.Series]:
    """Risk-on / risk-off rotation between a risk asset and a defensive asset.

    The **first holding** is the risk asset (e.g. an equity ETF); its own price
    drives the regime signal.  The **second holding**, if present, is the
    defensive asset (e.g. a bond ETF) that receives the budget during risk-off
    (with a single holding, risk-off goes to cash).

    Go *risk-on* (hold the risk asset) when its close is above the trend MA
    **and** its short-window realised volatility is below its own trailing
    long-run average.  Otherwise go *risk-off* (hold the defensive asset).
    The regime is decided from each day's close and applied on the **next bar**
    so there is no look-ahead.
    """
    ma_window = max(int(params.get("ma_window", 50)), 5)
    vol_window = max(int(params.get("vol_window", 20)), 5)
    vol_avg_window = max(int(params.get("vol_avg_window", 252)), vol_window * 2)

    codes = [_to_code(h) for h in holdings if _to_code(h) in data_map]
    if not codes:
        return {}
    risk_code = codes[0]
    safe_code = codes[1] if len(codes) > 1 else None
    total_budget = min(
        sum(_weight(h) for h in holdings if _to_code(h) in data_map), 1.0
    )

    risk_close = data_map[risk_code]["close"].astype(float)
    if risk_close.empty:
        return {}

    ma = risk_close.rolling(ma_window, min_periods=max(5, ma_window // 2)).mean()
    vol = risk_close.pct_change().rolling(
        vol_window, min_periods=max(3, vol_window // 2)
    ).std()
    vol_avg = vol.rolling(
        vol_avg_window, min_periods=max(20, vol_avg_window // 4)
    ).mean()

    uptrend = risk_close > ma
    calm = vol < vol_avg
    # Decide at the close, act next bar.
    risk_on = (uptrend & calm).shift(1).fillna(False).astype(bool)

    risk_idx = risk_close.index
    risk_w = pd.Series(0.0, index=risk_idx)
    risk_w[risk_on] = total_budget
    signal_map: Dict[str, pd.Series] = {risk_code: risk_w}

    if safe_code is not None:
        safe_idx = data_map[safe_code].index
        # Map the regime onto the defensive asset's own calendar.
        regime_safe = (
            risk_on.reindex(risk_idx.union(safe_idx))
            .ffill()
            .reindex(safe_idx)
            .fillna(False)
            .astype(bool)
        )
        safe_w = pd.Series(0.0, index=safe_idx)
        safe_w[~regime_safe] = total_budget
        signal_map[safe_code] = safe_w

    return signal_map


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window, min_periods=max(2, window // 2)).mean()
    loss = (-delta.clip(upper=0)).rolling(window, min_periods=max(2, window // 2)).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50.0)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window, min_periods=max(2, window // 2)).mean()


def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    aligned = pd.concat([a, b], axis=1).dropna()
    if len(aligned) < 3:
        return 0.0
    if float(aligned.iloc[:, 0].std()) == 0.0 or float(aligned.iloc[:, 1].std()) == 0.0:
        return 0.0
    value = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
    return float(value) if pd.notna(value) and np.isfinite(value) else 0.0


def _rank_feature(features: dict[str, dict[str, float]], key: str, ascending: bool) -> dict[str, float]:
    values = pd.Series({code: vals.get(key, 0.0) for code, vals in features.items()}, dtype=float)
    if values.empty:
        return {}
    ranks = values.rank(method="average", ascending=ascending, pct=True)
    return {code: float(score) for code, score in ranks.items()}


def _to_code(holding: PaperHolding) -> str:
    """Build the internal code used by backtest loaders.

    US equities use ``AAPL.US`` format, HK equities use ``0700.HK``, and
    A-shares use the yfinance exchange suffix (``600519.SS`` for Shanghai,
    ``300750.SZ`` for Shenzhen). The user may already supply suffixed symbols;
    normalise either way.
    """
    symbol = holding.symbol.strip().upper()
    if holding.market == "hk":
        digits = symbol.replace(".HK", "")
        return f"{int(digits):04d}.HK"
    if holding.market == "cn":
        if symbol.endswith((".SS", ".SZ", ".BJ")):
            return symbol
        digits = "".join(ch for ch in symbol if ch.isdigit())
        # 6xxxxx/9xxxxx → Shanghai; 4xxxxx/8xxxxx → Beijing; else Shenzhen.
        if digits.startswith(("6", "9")):
            return f"{digits}.SS"
        if digits.startswith(("4", "8")):
            return f"{digits}.BJ"
        return f"{digits}.SZ"
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
    if strategy_name == "ma200_timing":
        return generate_ma200_timing(holdings, data_map, params)
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
    if strategy_name == "macd_divergence":
        return generate_macd_divergence(holdings, data_map, params)
    if strategy_name == "dual_momentum":
        return generate_dual_momentum(holdings, data_map, params)
    if strategy_name == "vol_trend_rotation":
        return generate_vol_trend_rotation(holdings, data_map, params)
    if strategy_name == "atr_trend_stop":
        return generate_atr_trend_stop(holdings, data_map, params)
    if strategy_name == "mean_reversion_scaleout":
        return generate_mean_reversion_scaleout(holdings, data_map, params)
    if strategy_name == "enhanced_dca_trend":
        return generate_enhanced_dca_trend(holdings, data_map, params)
    if strategy_name == "breakout_pullback":
        return generate_breakout_pullback(holdings, data_map, params)
    if strategy_name == "quality_momentum":
        return generate_quality_momentum(holdings, data_map, params)
    if strategy_name == "low_volatility_rotation":
        return generate_low_volatility_rotation(holdings, data_map, params)
    if strategy_name == "volatility_squeeze_breakout":
        return generate_volatility_squeeze_breakout(holdings, data_map, params)
    if strategy_name == "risk_parity":
        return generate_risk_parity(holdings, data_map, params)
    if strategy_name == "price_volume_efficiency":
        return generate_price_volume_efficiency(holdings, data_map, params)
    raise ValueError(f"Unknown strategy: {strategy_name}")
