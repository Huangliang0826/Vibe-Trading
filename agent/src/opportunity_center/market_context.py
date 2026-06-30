"""Deterministic market context inputs for opportunity scoring."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from backtest.loaders.yfinance_loader import DataLoader as YFinanceLoader
from src.opportunity_center.models import MarketContext, Market
from src.paper_trading.hstech_best import normalize_best_strategy_symbol


def load_market_context(market: Market, code: str, as_of: date) -> MarketContext:
    _paper_symbol, loader_code, display_code = normalize_best_strategy_symbol(code, market)
    frame = _load_price_history(loader_code, start_date="2020-01-01", as_of=as_of)
    valuation_percentile = None
    if market == "hk":
        valuation_percentile = _valuation_percentile(_fetch_hk_valuation_history(display_code, as_of))
    return _compute_market_context(frame, market=market, code=display_code, as_of=as_of, valuation_percentile=valuation_percentile)


def _compute_market_context(
    frame: pd.DataFrame,
    market: Market,
    code: str,
    as_of: date,
    valuation_percentile: float | None,
) -> MarketContext:
    trimmed = _trim_frame(frame, as_of)
    close = trimmed["close"].astype(float)
    volume = trimmed["volume"].astype(float)
    returns = close.pct_change().dropna()

    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    momentum63 = float(close.iloc[-1] / close.iloc[-64] - 1)
    annual_vol = float(returns.tail(63).std() * math.sqrt(252))
    downside_vol = float(returns.tail(63).clip(upper=0).std() * math.sqrt(252))
    max_drawdown = float((close / close.cummax() - 1).min())
    volume_ratio = float(volume.tail(20).mean() / volume.tail(60).mean())
    volume_confirmation = 10.0 if momentum63 > 0 and volume_ratio >= 1.2 else -10.0 if momentum63 < 0 and volume_ratio >= 1.2 else 0.0

    trend_score = _clamp(
        50.0
        + (15.0 if float(close.iloc[-1]) > sma200 else -15.0)
        + (10.0 if sma50 > sma200 else -10.0)
        + _clamp(momentum63 * 100.0, lower=-15.0, upper=15.0)
        + volume_confirmation
    )
    risk_score = _clamp(
        100.0
        - min(annual_vol, 1.0) * 45.0
        - min(abs(max_drawdown), 1.0) * 40.0
        - min(downside_vol, 1.0) * 15.0
    )

    return MarketContext(
        market=market,
        code=code,
        latest_price_date=trimmed.index[-1].date().isoformat(),
        trend_score=trend_score,
        risk_score=risk_score,
        trend_inputs={
            "close": float(close.iloc[-1]),
            "sma50": sma50,
            "sma200": sma200,
            "momentum63": momentum63,
            "volume_ratio": volume_ratio,
        },
        risk_inputs={
            "annual_vol": annual_vol,
            "downside_vol": downside_vol,
            "max_drawdown": max_drawdown,
        },
        valuation_percentile=valuation_percentile,
    )


def _load_price_history(code: str, start_date: str, as_of: date) -> pd.DataFrame:
    loader = YFinanceLoader()
    data = loader.fetch([code], start_date, as_of.isoformat(), interval="1D")
    frame = data.get(code)
    if frame is None or frame.empty:
        raise ValueError(f"No price data fetched for {code}")
    return frame


def _trim_frame(frame: pd.DataFrame, as_of: date) -> pd.DataFrame:
    trimmed = frame.copy()
    trimmed.index = pd.DatetimeIndex(pd.to_datetime(trimmed.index)).tz_localize(None)
    trimmed = trimmed.sort_index()
    trimmed = trimmed.loc[trimmed.index.date <= as_of].copy()
    if trimmed.empty:
        raise ValueError("No market data available on or before as_of")
    if len(trimmed) < 200:
        raise ValueError("Market context requires at least 200 trading rows")
    return trimmed


def _fetch_hk_valuation_history(code: str, as_of: date) -> pd.DataFrame | None:
    try:
        from api_server import _fetch_valuation_history
    except Exception:
        return None

    pe_points = _fetch_valuation_history(code, "hk", "pe", "5Y")
    pb_points = _fetch_valuation_history(code, "hk", "pb", "5Y")
    if not pe_points and not pb_points:
        return None

    series: dict[str, dict[str, float]] = {}
    cutoff = as_of.isoformat()
    for name, points in (("pe", pe_points), ("pb", pb_points)):
        for point in points:
            point_date = str(point.get("date") or "")[:10]
            if not point_date or point_date > cutoff:
                continue
            try:
                value = float(point.get("value"))
            except (TypeError, ValueError):
                continue
            series.setdefault(point_date, {})[name] = value

    if not series:
        return None
    frame = pd.DataFrame.from_dict(series, orient="index").sort_index()
    frame.index = pd.DatetimeIndex(frame.index)
    return frame


def _valuation_percentile(history: pd.DataFrame | None) -> float | None:
    if history is None or history.empty:
        return None

    pe_values = _positive_series(history.get("pe"))
    if len(pe_values) >= 30:
        return _series_percentile(pe_values)

    pb_values = _positive_series(history.get("pb"))
    if len(pb_values) >= 30:
        return _series_percentile(pb_values)
    return None


def _positive_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric[(numeric > 0) & np.isfinite(numeric)].dropna()


def _series_percentile(series: pd.Series) -> float | None:
    if series.empty:
        return None
    latest = float(series.iloc[-1])
    rank = float((series <= latest).mean() * 100.0)
    return round(rank, 4)


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(value, upper))
