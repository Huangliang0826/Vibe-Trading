"""Shared backtest metrics, extracted from daily_portfolio.py for reuse.

Provides annualisation helpers, trade statistics, and full metric calculation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.models import TradeRecord


_PATH_METRIC_KEYS = (
    "total_return",
    "annual_return",
    "max_drawdown",
    "max_loss",
    "sharpe",
    "calmar",
    "sortino",
)


def validate_price_series(prices: pd.Series, *, name: str = "prices") -> pd.Series:
    """Return a sorted numeric price series after strict validity checks.

    All price-based metrics use this gate. Missing, non-finite, zero, and
    negative prices are rejected instead of silently contaminating returns.
    Duplicate timestamps are also rejected because their ordering changes
    path-dependent metrics such as drawdown and DCA.
    """
    if not isinstance(prices, pd.Series):
        raise TypeError(f"{name} must be a pandas Series")
    if prices.empty:
        return prices.astype(float)
    series = pd.to_numeric(prices, errors="coerce").astype(float)
    values = series.to_numpy()
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError(f"{name} must contain only finite positive values")
    if series.index.has_duplicates:
        raise ValueError(f"{name} must not contain duplicate timestamps")
    return series.sort_index()


def _path_metric_summary(equity_curve: pd.Series, initial_cash: float, bars_per_year: int) -> Dict[str, float]:
    """Calculate the common display subset for a positive equity path."""
    metrics = calc_metrics(equity_curve, [], initial_cash, bars_per_year)
    return {key: float(metrics[key]) for key in _PATH_METRIC_KEYS}


def compute_price_path_metrics(prices: pd.Series, *, bars_per_year: int = 252) -> Dict[str, float]:
    """Compute canonical buy-and-hold metrics for a positive close series.

    Prices are normalized to one unit of starting capital, so the result is
    independent of whether the source is quoted in HKD, USD, or CNY.
    """
    series = validate_price_series(prices)
    if series.empty:
        return _path_metric_summary(pd.Series(dtype=float), 1.0, bars_per_year)
    equity = series / float(series.iloc[0])
    return _path_metric_summary(equity, 1.0, bars_per_year)


def compute_daily_dca_metrics(prices: pd.Series, *, bars_per_year: int = 252) -> Dict[str, float | int]:
    """Compute canonical daily-DCA metrics from a close series.

    One equal cash contribution is made on the first available bar and once
    per distinct calendar date thereafter. Contributions are invested at that
    day's close, then the resulting marked-to-market NAV is measured against
    total contributed capital. Intraday bars therefore contribute at most once
    per session.
    """
    series = validate_price_series(prices)
    if series.empty:
        result = _path_metric_summary(pd.Series(dtype=float), 1.0, bars_per_year)
        result["contributions"] = 0
        return result

    try:
        date_keys = pd.to_datetime(series.index).date
    except (TypeError, ValueError):
        date_keys = list(range(len(series)))

    units = 1.0 / float(series.iloc[0])
    contributed = 1.0
    nav = [1.0]
    last_date = date_keys[0]
    for price, current_date in zip(series.iloc[1:], date_keys[1:]):
        if current_date != last_date:
            units += 1.0 / float(price)
            contributed += 1.0
            last_date = current_date
        nav.append(units * float(price) / contributed)

    result = _path_metric_summary(pd.Series(nav, index=series.index), 1.0, bars_per_year)
    result["contributions"] = int(contributed)
    return result

# ─── Annualisation factor mapping ───

# mootdx (A-share) and futu (HK + A-share) are equity sources, so they mirror
# the tushare/akshare column: 252 trading days and a 240-minute session. HK
# sessions are marginally longer (~330 min) — an approximation in line with the
# rest of this annualisation table; the key fix is that intraday mootdx/futu no
# longer fall back to the bars_per_day=1 default, which mis-annualised vol/Sharpe.
_TRADING_DAYS = {"tushare": 252, "yfinance": 252, "okx": 365, "akshare": 252, "ccxt": 365, "mootdx": 252, "futu": 252}
_BARS_PER_DAY = {
    "1m":  {"tushare": 240, "okx": 1440, "yfinance": 390, "akshare": 240, "ccxt": 1440, "mootdx": 240, "futu": 240},
    "5m":  {"tushare": 48,  "okx": 288,  "yfinance": 78,  "akshare": 48,  "ccxt": 288,  "mootdx": 48,  "futu": 48},
    "15m": {"tushare": 16,  "okx": 96,   "yfinance": 26,  "akshare": 16,  "ccxt": 96,   "mootdx": 16,  "futu": 16},
    "30m": {"tushare": 8,   "okx": 48,   "yfinance": 13,  "akshare": 8,   "ccxt": 48,   "mootdx": 8,   "futu": 8},
    "1H":  {"tushare": 4,   "okx": 24,   "yfinance": 7,   "akshare": 4,   "ccxt": 24,   "mootdx": 4,   "futu": 4},
    "4H":  {"tushare": 1,   "okx": 6,    "yfinance": 2,   "akshare": 1,   "ccxt": 6,    "mootdx": 1,   "futu": 1},
    "1D":  {"tushare": 1,   "okx": 1,    "yfinance": 1,   "akshare": 1,   "ccxt": 1,    "mootdx": 1,   "futu": 1},
}


def calc_bars_per_year(interval: str = "1D", source: str = "tushare") -> int:
    """Number of bars per year for annualisation.

    Args:
        interval: Bar size (1m / 5m / 15m / 30m / 1H / 4H / 1D).
        source: Data source (tushare / yfinance / okx).

    Returns:
        Bars per year.
    """
    trading_days = _TRADING_DAYS.get(source, 252)
    bars_per_day = _BARS_PER_DAY.get(interval, {}).get(source, 1)
    return trading_days * bars_per_day


def win_rate_and_stats(trades: List[TradeRecord]) -> Dict[str, float]:
    """Win rate and P&L statistics from completed trades.

    Args:
        trades: Completed round-trip trades.

    Returns:
        Dict with win_rate, profit_loss_ratio, max_consecutive_loss,
        avg_holding_bars, profit_factor.
    """
    if not trades:
        return {
            "win_rate": 0.0,
            "profit_loss_ratio": 0.0,
            "max_consecutive_loss": 0,
            "avg_holding_bars": 0.0,
            "profit_factor": 0.0,
        }

    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl < 0]

    win_rate = len(wins) / len(trades)

    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = abs(float(np.mean(losses))) if losses else 1e-10
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 1e-10 else 0.0

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 1e-10
    profit_factor = gross_profit / gross_loss if gross_loss > 1e-10 else 0.0

    max_consec = 0
    cur_consec = 0
    for t in trades:
        if t.pnl < 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    hold_bars = [t.holding_bars for t in trades if t.holding_bars > 0]
    avg_holding = float(np.mean(hold_bars)) if hold_bars else 0.0

    return {
        "win_rate": win_rate,
        "profit_loss_ratio": round(profit_loss_ratio, 4),
        "max_consecutive_loss": max_consec,
        "avg_holding_bars": round(avg_holding, 1),
        "profit_factor": round(profit_factor, 4),
    }


def by_symbol_stats(trades: List[TradeRecord]) -> Dict[str, Dict[str, Any]]:
    """Per-symbol trade statistics.

    Args:
        trades: Completed round-trip trades.

    Returns:
        {symbol: {count, win_rate, total_pnl, avg_pnl}}.
    """
    groups: Dict[str, list] = {}
    for t in trades:
        groups.setdefault(t.symbol, []).append(t)

    result = {}
    for sym, sym_trades in groups.items():
        pnls = [t.pnl for t in sym_trades]
        wins = [p for p in pnls if p > 0]
        result[sym] = {
            "count": len(sym_trades),
            "win_rate": round(len(wins) / len(sym_trades), 4) if sym_trades else 0.0,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(float(np.mean(pnls)), 2) if pnls else 0.0,
        }
    return result


def by_exit_reason_stats(trades: List[TradeRecord]) -> Dict[str, Dict[str, Any]]:
    """Per-exit-reason trade statistics.

    Args:
        trades: Completed round-trip trades.

    Returns:
        {reason: {count, total_pnl}}.
    """
    groups: Dict[str, list] = {}
    for t in trades:
        groups.setdefault(t.exit_reason, []).append(t)

    result = {}
    for reason, reason_trades in groups.items():
        pnls = [t.pnl for t in reason_trades]
        result[reason] = {
            "count": len(reason_trades),
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def calc_metrics(
    equity_curve: pd.Series,
    trades: List[TradeRecord],
    initial_cash: float,
    bars_per_year: Optional[int] = 252,
    bench_ret: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Full set of performance metrics.

    Args:
        equity_curve: Equity time series (index=timestamp, values=equity).
        trades: Completed round-trip trades.
        initial_cash: Starting capital.
        bars_per_year: Bars per year for annualisation. None = auto-detect
            from equity curve dates (calendar-day method, for cross-market).
        bench_ret: Benchmark per-bar return series (optional).

    Returns:
        Metrics dictionary (compatible with daily_portfolio format).
    """
    if len(equity_curve) == 0:
        return _empty_metrics(initial_cash)

    n = len(equity_curve)

    # Calendar-day annualization for cross-market (bars_per_year=None)
    if bars_per_year is None:
        first, last = equity_curve.index[0], equity_curve.index[-1]
        calendar_days = (last - first).days
        years = calendar_days / 365.25 if calendar_days > 0 else 1.0
        bpy = int(n / years) if years > 0 else 252
    else:
        bpy = bars_per_year

    port_ret = equity_curve.pct_change().fillna(0.0)

    total_ret = float(equity_curve.iloc[-1] / initial_cash - 1)
    ann_ret = float((1 + total_ret) ** (bpy / max(n, 1)) - 1)
    vol = float(port_ret.std())
    annual_vol = float(vol * np.sqrt(bpy))
    sharpe = float(port_ret.mean() / (vol + 1e-10) * np.sqrt(bpy))

    # Drawdown
    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak.replace(0, 1)
    max_dd = float(dd.min())

    # Max loss relative to the initial capital: the worst the portfolio ever
    # sank below the money actually put in. Unlike max drawdown (peak→trough,
    # which can be large even when the account never went below principal),
    # this is 0 if equity never dipped under the starting cash.
    max_loss = float(min(0.0, equity_curve.min() / initial_cash - 1)) if initial_cash > 0 else 0.0

    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-10 else 0.0

    # Sortino
    downside = port_ret[port_ret < 0]
    downside_std = float(downside.std()) if len(downside) > 1 else 1e-10
    sortino = float(port_ret.mean() / (downside_std + 1e-10) * np.sqrt(bpy))

    trade_stats = win_rate_and_stats(trades)

    # Benchmark comparison
    bench_return = 0.0
    excess = 0.0
    ir = 0.0
    if bench_ret is not None and len(bench_ret) > 0:
        bench_return = float((1 + bench_ret).prod() - 1)
        excess = total_ret - bench_return
        active_ret = port_ret - bench_ret.reindex(port_ret.index).fillna(0.0)
        active_std = float(active_ret.std())
        ir = float(active_ret.mean() / (active_std + 1e-10) * np.sqrt(bpy))

    return {
        "final_value": float(equity_curve.iloc[-1]),
        "total_return": total_ret,
        "annual_return": ann_ret,
        "annual_vol": annual_vol,
        "max_drawdown": max_dd,
        "max_loss": max_loss,
        "sharpe": sharpe,
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "win_rate": trade_stats["win_rate"],
        "profit_loss_ratio": trade_stats["profit_loss_ratio"],
        "profit_factor": trade_stats["profit_factor"],
        "max_consecutive_loss": trade_stats["max_consecutive_loss"],
        "avg_holding_days": trade_stats["avg_holding_bars"],
        "trade_count": len(trades),
        "benchmark_return": round(bench_return, 6),
        "excess_return": round(excess, 6),
        "information_ratio": round(ir, 4),
    }


def _empty_metrics(initial_cash: float) -> Dict[str, Any]:
    """Return zero-valued metrics when no data is available."""
    return {
        "final_value": initial_cash,
        "total_return": 0, "annual_return": 0, "annual_vol": 0,
        "max_drawdown": 0, "max_loss": 0,
        "sharpe": 0, "calmar": 0, "sortino": 0,
        "win_rate": 0, "profit_loss_ratio": 0, "profit_factor": 0,
        "max_consecutive_loss": 0, "avg_holding_days": 0, "trade_count": 0,
        "benchmark_return": 0, "excess_return": 0, "information_ratio": 0,
    }
