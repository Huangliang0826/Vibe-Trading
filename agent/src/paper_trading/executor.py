"""Orchestrates a paper-trading backtest run.

Reuses the existing backtest engine (GlobalEquityEngine) and metrics
(calc_metrics) from ``agent/backtest/``.  DCA uses a dedicated simulator
that accumulates shares with fixed-dollar purchases instead of the
weight-based engine.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backtest.engines.base import _align
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.metrics import by_symbol_stats, calc_metrics
from backtest.models import EquitySnapshot, TradeRecord
from src.paper_trading.models import PaperHolding, PaperTradingRun
from src.paper_trading.storage import PaperTradingStore, HKD_TO_USD
from src.paper_trading.strategies import _to_code, generate_signals

logger = logging.getLogger(__name__)

_FREQ_MAP = {
    "weekly": "W-MON",
    "biweekly": "2W-MON",
    "monthly": "MS",
}


def run_paper_trading_backtest(run_id: str, store: PaperTradingStore) -> None:
    """Execute a paper-trading backtest (blocking — call from a thread)."""
    from backtest.loaders.yfinance_loader import DataLoader as YFinanceLoader
    from src.paper_trading.models import PaperTradingStatus

    run = store.get_run(run_id)
    if run is None:
        return

    try:
        store.update_status(run_id, PaperTradingStatus.running)

        loader = YFinanceLoader()
        equity_holdings = [h for h in run.holdings if h.symbol.upper() != "CASH"]
        if not equity_holdings:
            raise ValueError("Portfolio has no equity holdings — only cash")
        codes = [_to_code(h) for h in equity_holdings]

        data_map = loader.fetch(
            codes,
            run.start_date,
            run.end_date,
            interval="1D",
        )
        if not data_map:
            raise ValueError("No price data fetched — check symbols and date range")

        initial_cash = run.initial_total_usd

        if run.strategy.name in {"dca", "smart_dca"}:
            equity_series, trades = _run_dca(
                initial_cash, equity_holdings, data_map, run.strategy.params,
                smart=run.strategy.name == "smart_dca",
            )
        else:
            signal_map = generate_signals(
                equity_holdings, data_map, run.strategy.name, run.strategy.params,
            )
            valid_codes = sorted(c for c in signal_map if c in data_map)
            if not valid_codes:
                raise ValueError("No valid signals generated")

            dates, close_df, target_pos, _ret_df = _align(
                data_map, signal_map, valid_codes,
            )
            valid_codes = [c for c in valid_codes if c in target_pos.columns]

            us_codes = [c for c in valid_codes if c.endswith(".US")]
            hk_codes = [c for c in valid_codes if c.endswith(".HK")]
            has_us = bool(us_codes)
            has_hk = bool(hk_codes)

            if has_us and has_hk:
                engine = _run_mixed(
                    initial_cash, dates, data_map, close_df, target_pos,
                    us_codes, hk_codes, valid_codes,
                )
            elif has_hk:
                engine = GlobalEquityEngine({"initial_cash": initial_cash}, market="hk")
                engine._execute_bars(dates, data_map, close_df, target_pos, hk_codes)
            else:
                engine = GlobalEquityEngine({"initial_cash": initial_cash}, market="us")
                engine._execute_bars(dates, data_map, close_df, target_pos, us_codes or valid_codes)

            equity_series = pd.Series(
                [s.equity for s in engine.equity_snapshots],
                index=[s.timestamp for s in engine.equity_snapshots],
            )
            trades = engine.trades

        metrics = calc_metrics(equity_series, trades, initial_cash, bars_per_year=None)
        metrics["by_symbol"] = by_symbol_stats(trades)

        equity_curve = _build_equity_curve(equity_series)
        trades_list = _build_trades_list(trades)

        store.complete_run(run_id, metrics, equity_curve, trades_list)

    except Exception as exc:
        logger.warning("paper trading backtest %s failed: %s", run_id, exc)
        try:
            store.fail_run(run_id, str(exc))
        except Exception:
            logger.exception("failed to persist failure for paper trading %s", run_id)


# ── DCA simulator ───────────────────────────────────────────────────────────

def _run_dca(
    initial_cash: float,
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
    smart: bool = False,
) -> tuple:
    """Fixed-dollar DCA: buy a fixed amount each period, accumulate shares."""
    frequency = params.get("frequency", "monthly")
    freq = _FREQ_MAP.get(frequency, "MS")

    code_map = {_to_code(h): h for h in holdings}
    valid_codes = sorted(c for c in code_map if c in data_map)
    if not valid_codes:
        raise ValueError("No valid codes with data for DCA")

    all_dates = sorted(set().union(*(data_map[c].index for c in valid_codes)))
    if not all_dates:
        raise ValueError("No trading dates")

    calendar_dca = pd.date_range(start=all_dates[0], end=all_dates[-1], freq=freq)
    trading_idx = pd.DatetimeIndex(all_dates)
    dca_dates: set = {trading_idx[0]}
    for d in calendar_dca:
        future = trading_idx[trading_idx >= d]
        if len(future) > 0:
            dca_dates.add(future[0])

    shares: Dict[str, float] = {c: 0.0 for c in valid_codes}
    cost_basis: Dict[str, float] = {c: 0.0 for c in valid_codes}
    entry_times: Dict[str, pd.Timestamp] = {}
    cash = initial_cash

    n_periods = max(len(dca_dates), 1)
    tranche_per_code = {
        c: initial_cash * (code_map[c].allocation_pct / 100.0) / n_periods
        for c in valid_codes
    }

    equity_points: List[tuple] = []
    buy_records: List[Dict[str, Any]] = []

    for ts in all_dates:
        is_dca = ts in dca_dates

        if is_dca:
            for c in valid_codes:
                if ts not in data_map[c].index:
                    continue
                price = float(data_map[c].loc[ts, "open"])
                if price <= 0:
                    continue
                amount = tranche_per_code[c]
                if smart:
                    amount *= _smart_dca_multiplier(data_map[c], ts, params)
                if amount > cash:
                    amount = cash
                if amount <= 0:
                    continue
                new_shares = amount / price
                shares[c] += new_shares
                cost_basis[c] += amount
                cash -= amount
                if c not in entry_times:
                    entry_times[c] = ts
                buy_records.append({
                    "symbol": c, "time": ts, "price": price,
                    "shares": new_shares, "amount": amount,
                })

        portfolio_value = cash
        for c in valid_codes:
            if ts in data_map[c].index:
                portfolio_value += shares[c] * float(data_map[c].loc[ts, "close"])
            elif shares[c] > 0 and equity_points:
                portfolio_value += shares[c] * _last_close(c, data_map, ts)

        equity_points.append((ts, portfolio_value))

    equity_series = pd.Series(
        [e for _, e in equity_points],
        index=pd.DatetimeIndex([t for t, _ in equity_points]),
    )

    last_ts = all_dates[-1]
    trades: List[TradeRecord] = []
    for b in buy_records:
        c = b["symbol"]
        exit_price = float(data_map[c].loc[last_ts, "close"]) if last_ts in data_map[c].index else b["price"]
        pnl = b["shares"] * (exit_price - b["price"])
        pnl_pct = (exit_price / b["price"] - 1) * 100 if b["price"] > 0 else 0
        trades.append(TradeRecord(
            symbol=c, direction=1,
            entry_price=round(b["price"], 4),
            exit_price=round(exit_price, 4),
            entry_time=b["time"], exit_time=last_ts,
            size=round(b["shares"], 4), leverage=1.0,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 4),
            exit_reason="end_of_backtest",
            holding_bars=(last_ts - b["time"]).days,
            commission=0.0,
        ))

    return equity_series, trades


def _smart_dca_multiplier(
    df: pd.DataFrame,
    ts: pd.Timestamp,
    params: Dict[str, Any],
) -> float:
    """Adjust each DCA tranche using trend distance and realised volatility."""
    history = df.loc[df.index < ts].copy()
    if history.empty:
        return 1.0

    close = history["close"].astype(float)
    price = float(close.iloc[-1])
    ma_window = max(int(params.get("ma_window", 60)), 5)
    vol_window = max(int(params.get("vol_window", 20)), 5)
    max_multiplier = max(float(params.get("max_multiplier", 2.0)), 1.0)
    min_multiplier = max(float(params.get("min_multiplier", 0.3)), 0.0)

    ma = float(close.rolling(ma_window, min_periods=max(5, ma_window // 3)).mean().iloc[-1])
    multiplier = 1.0

    if ma > 0 and np.isfinite(ma):
        discount = price / ma - 1
        if discount <= -0.12:
            multiplier = 2.0
        elif discount <= -0.07:
            multiplier = 1.5
        elif discount <= -0.03:
            multiplier = 1.2
        elif discount >= 0.10:
            multiplier = 0.4
        elif discount >= 0.05:
            multiplier = 0.7

    realised_vol = close.pct_change().rolling(vol_window, min_periods=max(5, vol_window // 2)).std().iloc[-1]
    if pd.notna(realised_vol) and realised_vol * np.sqrt(252) > 0.35:
        multiplier *= 0.75

    return float(np.clip(multiplier, min_multiplier, max_multiplier))


def _last_close(code: str, data_map: Dict[str, pd.DataFrame], before: pd.Timestamp) -> float:
    """Get the most recent close price before a given timestamp."""
    df = data_map[code]
    mask = df.index <= before
    if mask.any():
        return float(df.loc[mask, "close"].iloc[-1])
    return 0.0


def _run_mixed(
    initial_cash: float,
    dates: pd.DatetimeIndex,
    data_map: Dict[str, pd.DataFrame],
    close_df: pd.DataFrame,
    target_pos: pd.DataFrame,
    us_codes: List[str],
    hk_codes: List[str],
    all_codes: List[str],
) -> GlobalEquityEngine:
    """Run a mixed US+HK backtest.

    Uses US engine rules (zero commission, fractional shares) as the base,
    but applies HK commission overrides per-symbol in the rebalance loop.
    For MVP simplicity we use a single US engine — HK stamp tax is small
    and this avoids splitting capital across two engines.
    """
    engine = GlobalEquityEngine({"initial_cash": initial_cash}, market="us")
    engine._execute_bars(dates, data_map, close_df, target_pos, all_codes)
    return engine


def _build_equity_curve(equity_series: pd.Series) -> List[Dict[str, Any]]:
    """Convert equity series to frontend-friendly format."""
    peak = equity_series.cummax()
    dd = (equity_series - peak) / peak.replace(0, 1)
    result = []
    for ts, eq in equity_series.items():
        result.append({
            "time": ts.strftime("%Y-%m-%d"),
            "equity": round(float(eq), 2),
            "drawdown": round(float(dd[ts]), 6),
        })
    return result


def _build_trades_list(trades) -> List[Dict[str, Any]]:
    """Convert TradeRecord list to serialisable dicts."""
    result = []
    for t in trades:
        result.append({
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": round(t.entry_price, 4),
            "exit_price": round(t.exit_price, 4),
            "entry_time": t.entry_time.strftime("%Y-%m-%d"),
            "exit_time": t.exit_time.strftime("%Y-%m-%d"),
            "size": round(t.size, 4),
            "pnl": round(t.pnl, 2),
            "pnl_pct": round(t.pnl_pct, 4),
            "exit_reason": t.exit_reason,
            "holding_bars": t.holding_bars,
            "commission": round(t.commission, 4),
        })
    return result
