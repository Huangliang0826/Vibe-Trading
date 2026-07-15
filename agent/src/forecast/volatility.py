"""Volatility forecasting — what TimesFM is actually good at.

Financial price levels are near-random walks (unforecastable), but *volatility*
has memory, clusters, and mean-reversion — properties that time-series
foundation models genuinely capture. This module replaces the price-level
forecast with volatility-centric products:

1. **Volatility Forecast** — predict future 21-day realized vol (annualized)
   using TimesFM. The confidence cone here is *informative* because vol has
   a bounded, mean-reverting range (unlike prices).

2. **Volatility Regime** — classify current vol as low / normal / high
   relative to its trailing 2-year history.

3. **Risk Overlay** — when forecast vol is elevated, suggest reduced
   position sizing as a risk-management overlay.

All values are annualized so they're comparable across assets and timeframes.
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from src.forecast import engine

logger = logging.getLogger(__name__)

# ── Constants ──
_TRADING_DAYS = 252
_DEFAULT_VOL_WINDOW = 21         # ~1 calendar month for realized vol
_FORECAST_HORIZON = 63           # ~3 months forward vol forecast
_REGIME_WINDOW = 504             # ~2 years for regime percentile
_MIN_HISTORY = 252               # need at least 1 year for meaningful vol


# ══════════════════════════════════════════════════════════════════════════════
# Core computation
# ══════════════════════════════════════════════════════════════════════════════


def daily_returns(closes: list[float]) -> list[float]:
    """Simple daily returns from a close-price series.

    Returns empty list if fewer than 2 valid closes.
    """
    arr = np.asarray(closes, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return []
    rets = (arr[1:] / arr[:-1]) - 1.0
    # Clip extreme outliers (>50% daily move is almost certainly bad data)
    return [float(x) for x in np.clip(rets, -0.5, 0.5)]


def realized_vol(
    returns: list[float],
    window: int = _DEFAULT_VOL_WINDOW,
) -> list[float]:
    """Rolling realized volatility, annualized.

    Each entry is the annualized std of the trailing ``window`` daily returns.
    The first ``window - 1`` entries will be NaN; callers should drop them.
    """
    if len(returns) < window:
        return [float("nan")] * len(returns)
    arr = np.asarray(returns, dtype=float)
    rv = pd.Series(arr).rolling(window).std().to_numpy() * math.sqrt(_TRADING_DAYS)
    return [float(x) if not math.isnan(x) else x for x in rv]


def _clean_rv(returns: list[float], window: int) -> np.ndarray:
    """Compute rolling realized vol and drop leading NaNs.

    Returns a 1-D array of (n - window + 1) floats. Raises ``ValueError``
    if the resulting series is too short for meaningful forecasting.
    """
    rv = realized_vol(returns, window)
    clean = np.asarray([v for v in rv if not (isinstance(v, float) and math.isnan(v))], dtype=float)
    if clean.size < _MIN_HISTORY:
        raise ValueError(
            f"need >= {_MIN_HISTORY} vol observations "
            f"(requires ~{_MIN_HISTORY + window} trading days), got {clean.size}"
        )
    return clean


# ══════════════════════════════════════════════════════════════════════════════
# Volatility forecast (TimesFM on realized-vol series)
# ══════════════════════════════════════════════════════════════════════════════


def forecast_vol(
    closes: list[float],
    horizon: int = _FORECAST_HORIZON,
    vol_window: int = _DEFAULT_VOL_WINDOW,
    context: int | None = None,
) -> dict:
    """Forecast future realized volatility with TimesFM.

    Pipeline:
        1. Daily returns from closes
        2. Rolling realized vol (annualized)
        3. TimesFM forecast on the vol series (not on prices)
        4. Clip forecasts to [0, inf) — vol can't be negative

    Returns the same shape as ``engine.forecast()`` (point, p10, p50, p90,
    context_used) **expressed in annualized volatility percentage points**.
    All values are in the same unit (e.g. 0.25 = 25% annualized vol).

    Raises ``engine.TimesFMUnavailable`` if the model isn't installed.
    """
    rets = daily_returns(closes)
    if len(rets) < vol_window + 32:
        return {"error": f"insufficient_data: need {vol_window + 32} returns, got {len(rets)}"}

    rv_clean = _clean_rv(rets, vol_window)

    # Feed the vol series to TimesFM
    result = engine.forecast(rv_clean.tolist(), horizon, context=context)

    # Clip: negative volatility is impossible
    for key in ("point", "p10", "p50", "p90"):
        if result.get(key):
            result[key] = [max(0.0, float(v)) for v in result[key]]

    result["vol_window"] = vol_window
    result["input_unit"] = "annualized_vol"
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Regime classification
# ══════════════════════════════════════════════════════════════════════════════


def _percentile(value: float, history: list[float]) -> float:
    """What percentile is ``value`` within ``history``? 0.0–1.0."""
    arr = np.asarray(history, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.5
    return float(np.mean(arr <= value))


def vol_regime(
    closes: list[float],
    vol_window: int = _DEFAULT_VOL_WINDOW,
    regime_window: int = _REGIME_WINDOW,
) -> dict:
    """Classify the current vol regime.

    Returns:
        ``current_vol`` — latest realized vol (annualized)
        ``median_vol`` — trailing median
        ``percentile`` — where current vol sits vs trailing history (0-1)
        ``regime`` — "low" (p < 0.25), "normal" (0.25 ≤ p ≤ 0.75), "high" (p > 0.75)
    """
    rets = daily_returns(closes)
    if len(rets) < 2:
        return {"error": "insufficient_data", "current_vol": None}

    rv_clean = _clean_rv(rets, vol_window)
    current = float(rv_clean[-1])
    hist = rv_clean[-regime_window:].tolist() if rv_clean.size > regime_window else rv_clean.tolist()

    p = _percentile(current, hist)
    median = float(np.median(hist))

    if p < 0.25:
        label = "low"
    elif p > 0.75:
        label = "high"
    else:
        label = "normal"

    return {
        "current_vol": round(current, 6),
        "median_vol": round(median, 6),
        "percentile": round(p, 4),
        "regime": label,
        "history_size": len(hist),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Risk overlay: position-sizing signal from vol
# ══════════════════════════════════════════════════════════════════════════════


def risk_overlay(
    closes: list[float],
    vol_window: int = _DEFAULT_VOL_WINDOW,
) -> dict:
    """Suggest a position-sizing multiplier based on forecast vol.

    When forecast vol is above the trailing median, scale down exposure
    proportionally. The multiplier is 1.0 at median vol and decreases
    linearly to 0.5 at 2× median vol.

    Returns:
        ``multiplier`` — suggested position-size multiplier (0.5–1.0)
        ``forecast_vol_peak`` — peak forecast vol over the horizon
        ``current_vol`` — latest realized vol
        ``justification`` — human-readable explanation
    """
    rets = daily_returns(closes)
    if len(rets) < vol_window + 32:
        return {"error": "insufficient_data", "multiplier": 1.0}

    try:
        rv_clean = _clean_rv(rets, vol_window)
        fc = engine.forecast(rv_clean.tolist(), _FORECAST_HORIZON)
    except Exception:
        return {"error": "forecast_failed", "multiplier": 1.0}

    current_vol = float(rv_clean[-1])
    peak_fc = max(max(fc.get("p50", [current_vol])), current_vol)
    median_vol = float(np.median(rv_clean[-_REGIME_WINDOW:]))

    if median_vol <= 0:
        return {"multiplier": 1.0, "current_vol": current_vol,
                "forecast_vol_peak": peak_fc, "justification": "insufficient_vol_history"}

    ratio = peak_fc / median_vol
    multiplier = max(0.5, min(1.0, 2.0 - ratio))  # 1.0 at 1×, 0.5 at 2×+

    if ratio > 1.5:
        justification = f"高波动预警：预测波动率 {peak_fc:.1%} 为历史中位数 {median_vol:.1%} 的 {ratio:.1f} 倍，建议仓位降至 {multiplier:.0%}"
    elif ratio > 1.2:
        justification = f"波动上升：预测波动率 {peak_fc:.1%} 高于中位数 {median_vol:.1%}，建议仓位降至 {multiplier:.0%}"
    else:
        justification = f"波动正常：预测峰值 {peak_fc:.1%}，建议维持当前仓位"

    return {
        "multiplier": round(multiplier, 4),
        "forecast_vol_peak": round(peak_fc, 6),
        "current_vol": round(current_vol, 6),
        "median_vol": round(median_vol, 6),
        "ratio": round(ratio, 4),
        "justification": justification,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Combined endpoint payload
# ══════════════════════════════════════════════════════════════════════════════


def build_volatility_analysis(
    closes: list[float],
    horizon: int = _FORECAST_HORIZON,
) -> dict:
    """Full volatility analysis: forecast + regime + risk overlay.

    Returns a single dict that can be embedded in the API response.
    If the model is unavailable, returns partial data with ``model_error``.
    """
    result: dict = {"horizon": horizon, "model_available": engine.is_available()}

    # 1) Vol forecast
    try:
        result["forecast"] = forecast_vol(closes, horizon=horizon)
    except engine.TimesFMUnavailable:
        result["model_error"] = "timesfm_not_installed"
    except Exception as exc:
        logger.warning("vol forecast failed: %s", exc)
        result["model_error"] = str(exc)

    # 2) Regime
    try:
        result["regime"] = vol_regime(closes)
    except Exception as exc:
        logger.warning("vol regime failed: %s", exc)
        result["regime"] = {"error": str(exc)}

    # 3) Risk overlay
    try:
        result["risk_overlay"] = risk_overlay(closes)
    except Exception as exc:
        logger.warning("risk overlay failed: %s", exc)
        result["risk_overlay"] = {"error": str(exc)}

    # 4) Historical vol series for charting (trailing 2y)
    try:
        rets = daily_returns(closes)
        if rets:
            rv = realized_vol(rets)
            clean_rv = [v for v in rv if not (isinstance(v, float) and math.isnan(v))]
            if clean_rv:
                result["history_vol"] = clean_rv[-_REGIME_WINDOW:]
    except Exception as exc:
        logger.warning("vol history failed: %s", exc)

    return result
