"""Orchestrates a paper-trading backtest run.

Reuses the existing backtest engine (GlobalEquityEngine) and metrics
(calc_metrics) from ``agent/backtest/``.  DCA uses a dedicated simulator
that accumulates shares with fixed-dollar purchases instead of the
weight-based engine.
"""

from __future__ import annotations

import logging
from collections import deque
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

        equity_series, trades = evaluate_strategy(
            equity_holdings, data_map, run.strategy.name, run.strategy.params, initial_cash,
        )

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


# ── Strategy evaluation core ─────────────────────────────────────────────────

def evaluate_strategy(
    equity_holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    strategy_name: str,
    params: Dict[str, Any],
    initial_cash: float,
) -> tuple:
    """Run one strategy over a portfolio and return ``(equity_series, trades)``.

    Pure core shared by the single-run backtest and the multi-window robust
    optimiser — no persistence and no data fetching, so it can be called many
    times over sliced ``data_map`` views.
    """
    if strategy_name == "accelerated_dca_entry":
        return _run_accelerated_entry(
            initial_cash, equity_holdings, data_map, params,
        )

    if strategy_name == "deep_drawdown_recovery":
        return _run_deep_drawdown_recovery(
            initial_cash, equity_holdings, data_map, params,
        )

    if strategy_name in {"dca", "smart_dca", "dca_then_hold", "dca_one_year_then_hold", "dca_two_year_then_hold"}:
        deploy_years = None
        if strategy_name in {"dca_then_hold", "dca_one_year_then_hold", "dca_two_year_then_hold"}:
            default_years = {
                "dca_one_year_then_hold": 1,
                "dca_two_year_then_hold": 2,
                "dca_then_hold": 3,
            }[strategy_name]
            deploy_years = float(params.get("deploy_years", default_years))
        return _run_dca(
            initial_cash, equity_holdings, data_map, params,
            smart=strategy_name == "smart_dca",
            deploy_years=deploy_years,
        )

    signal_map = generate_signals(equity_holdings, data_map, strategy_name, params)
    valid_codes = sorted(c for c in signal_map if c in data_map)
    if not valid_codes:
        raise ValueError("No valid signals generated")

    dates, close_df, target_pos, _ret_df = _align(data_map, signal_map, valid_codes)
    valid_codes = [c for c in valid_codes if c in target_pos.columns]

    hk_codes = [c for c in valid_codes if c.endswith(".HK")]
    other_codes = [c for c in valid_codes if not c.endswith(".HK")]

    # Pure HK → HK engine (stamp tax + levies). Anything else — US, A-share
    # (.SS/.SZ), or a cross-market mix — runs on the US-rule engine (fractional
    # shares, negligible commission) over ALL codes, so A-share holdings are
    # never dropped from a mixed portfolio.
    if hk_codes and not other_codes:
        engine = GlobalEquityEngine({"initial_cash": initial_cash}, market="hk")
        engine._execute_bars(dates, data_map, close_df, target_pos, hk_codes)
    else:
        engine = GlobalEquityEngine({"initial_cash": initial_cash}, market="us")
        engine._execute_bars(dates, data_map, close_df, target_pos, valid_codes)

    equity_series = pd.Series(
        [s.equity for s in engine.equity_snapshots],
        index=[s.timestamp for s in engine.equity_snapshots],
    )
    return equity_series, engine.trades


# ── DCA simulator ───────────────────────────────────────────────────────────

_PERIODS_PER_YEAR = {"weekly": 52, "biweekly": 26, "monthly": 12}


def _run_dca(
    initial_cash: float,
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
    smart: bool = False,
    deploy_years: float | None = None,
) -> tuple:
    """Fixed-dollar DCA: buy a fixed amount each period, accumulate shares.

    ``deploy_years`` caps the deployment window: when set, all cash is split
    into ``deploy_years × periods/year`` equal tranches and invested only over
    the first ``deploy_years`` of the backtest, then simply held (no further
    buys). When ``None`` the cash is spread evenly across the whole backtest.
    """
    frequency = params.get("frequency", "monthly")
    freq = _FREQ_MAP.get(frequency, "MS")

    code_map = {_to_code(h): h for h in holdings}
    valid_codes = sorted(c for c in code_map if c in data_map)
    if not valid_codes:
        raise ValueError("No valid codes with data for DCA")

    all_dates = sorted(set().union(*(data_map[c].index for c in valid_codes)))
    if not all_dates:
        raise ValueError("No trading dates")

    trading_idx = pd.DatetimeIndex(all_dates)
    if deploy_years is not None:
        periods_per_year = _PERIODS_PER_YEAR.get(frequency, 12)
        n_window = max(int(round(deploy_years * periods_per_year)), 1)
        calendar_dca = pd.date_range(start=all_dates[0], periods=n_window, freq=freq)
    else:
        n_window = None
        calendar_dca = pd.date_range(start=all_dates[0], end=all_dates[-1], freq=freq)
    dca_dates: set = {trading_idx[0]}
    for d in calendar_dca:
        future = trading_idx[trading_idx >= d]
        if len(future) > 0:
            dca_dates.add(future[0])

    shares: Dict[str, float] = {c: 0.0 for c in valid_codes}
    cost_basis: Dict[str, float] = {c: 0.0 for c in valid_codes}
    entry_times: Dict[str, pd.Timestamp] = {}
    cash = initial_cash

    # Fixed-window mode sizes tranches by the full window so all cash is
    # deployed by its end; open-ended mode spreads across the actual DCA dates.
    n_periods = n_window if n_window is not None else max(len(dca_dates), 1)
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


def _run_accelerated_entry(
    initial_cash: float,
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> tuple:
    """Deploy 40% on T0, then accelerate six monthly tranches on drawdowns.

    T0 executes at that day's close. Later decisions execute at each month's
    first available open, using only that open and the already-known T0 close.
    Each holding owns an isolated budget sleeve based on its target allocation.
    """
    initial_pct = float(np.clip(float(params.get("initial_pct", 0.25)), 0.0, 1.0))
    n_months = max(int(params.get("n_months", 12)), 1)
    accelerate_drawdown = abs(float(params.get("accelerate_drawdown", 0.10)))
    all_in_drawdown = max(abs(float(params.get("all_in_drawdown", 0.20))), accelerate_drawdown)
    accelerated_investment_pct = float(np.clip(
        float(params.get("accelerated_investment_pct", 0.20)), 0.0, 1.0,
    ))

    code_map = {_to_code(h): h for h in holdings}
    valid_codes = sorted(c for c in code_map if c in data_map and not data_map[c].empty)
    if not valid_codes:
        raise ValueError("No valid codes with data for accelerated entry")

    all_dates = sorted(set().union(*(data_map[c].index for c in valid_codes)))
    if not all_dates:
        raise ValueError("No trading dates")

    t0_dates: Dict[str, pd.Timestamp] = {}
    t0_prices: Dict[str, float] = {}
    monthly_schedule: Dict[str, Dict[pd.Timestamp, int]] = {}
    sleeve_budget: Dict[str, float] = {}
    monthly_base: Dict[str, float] = {}
    sleeve_remaining: Dict[str, float] = {}
    shares: Dict[str, float] = {c: 0.0 for c in valid_codes}
    buy_records: List[Dict[str, Any]] = []
    equity_points: List[tuple] = []
    cash = initial_cash

    for code in valid_codes:
        frame = data_map[code].sort_index()
        t0 = pd.Timestamp(frame.index[0])
        t0_close = float(frame.loc[t0, "close"])
        if t0_close <= 0:
            continue
        budget = initial_cash * code_map[code].allocation_pct / 100.0
        t0_dates[code] = t0
        t0_prices[code] = t0_close
        sleeve_budget[code] = budget
        monthly_base[code] = budget * (1.0 - initial_pct) / n_months
        sleeve_remaining[code] = budget
        schedule: Dict[pd.Timestamp, int] = {}
        month_starts = pd.date_range(
            start=t0 + pd.offsets.MonthBegin(1), periods=n_months, freq="MS",
        )
        trading_idx = pd.DatetimeIndex(frame.index)
        for index, month_start in enumerate(month_starts):
            future = trading_idx[trading_idx >= month_start]
            if len(future) > 0:
                schedule[pd.Timestamp(future[0])] = n_months - index
        monthly_schedule[code] = schedule

    for ts in all_dates:
        ts = pd.Timestamp(ts)
        for code in valid_codes:
            if code not in t0_dates or ts not in data_map[code].index:
                continue
            amount = 0.0
            price = 0.0
            if ts == t0_dates[code]:
                price = t0_prices[code]
                amount = sleeve_remaining[code] * initial_pct
            elif ts in monthly_schedule[code] and sleeve_remaining[code] > 0:
                price = float(data_map[code].loc[ts, "open"])
                base = monthly_base[code]
                drawdown = price / t0_prices[code] - 1 if t0_prices[code] > 0 else 0.0
                if drawdown <= -all_in_drawdown + 1e-12:
                    amount = sleeve_remaining[code]
                elif drawdown <= -accelerate_drawdown + 1e-12:
                    amount = min(sleeve_budget[code] * accelerated_investment_pct, sleeve_remaining[code])
                else:
                    amount = base

            amount = min(amount, sleeve_remaining.get(code, 0.0), cash)
            if price <= 0 or amount <= 0:
                continue
            new_shares = amount / price
            shares[code] += new_shares
            sleeve_remaining[code] -= amount
            cash -= amount
            buy_records.append({
                "symbol": code, "time": ts, "price": price,
                "shares": new_shares, "amount": amount,
            })

        portfolio_value = cash
        for code in valid_codes:
            if ts in data_map[code].index:
                portfolio_value += shares[code] * float(data_map[code].loc[ts, "close"])
            elif shares[code] > 0:
                portfolio_value += shares[code] * _last_close(code, data_map, ts)
        equity_points.append((ts, portfolio_value))

    equity_series = pd.Series(
        [equity for _, equity in equity_points],
        index=pd.DatetimeIndex([timestamp for timestamp, _ in equity_points]),
    )
    last_ts = pd.Timestamp(all_dates[-1])
    trades: List[TradeRecord] = []
    for buy in buy_records:
        code = buy["symbol"]
        exit_price = (
            float(data_map[code].loc[last_ts, "close"])
            if last_ts in data_map[code].index else _last_close(code, data_map, last_ts)
        )
        pnl = buy["shares"] * (exit_price - buy["price"])
        trades.append(TradeRecord(
            symbol=code, direction=1,
            entry_price=round(buy["price"], 4), exit_price=round(exit_price, 4),
            entry_time=buy["time"], exit_time=last_ts,
            size=round(buy["shares"], 4), leverage=1.0,
            pnl=round(pnl, 2),
            pnl_pct=round((exit_price / buy["price"] - 1) * 100, 4),
            exit_reason="end_of_backtest",
            holding_bars=(last_ts - buy["time"]).days,
            commission=0.0,
        ))
    return equity_series, trades


def _run_deep_drawdown_recovery(
    initial_cash: float,
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    params: Dict[str, Any],
) -> tuple:
    """Stage entries after a three-year drawdown and exits after recovery."""
    drawdown_threshold = abs(float(params.get("drawdown_threshold", 0.40)))
    take_profit_pct = abs(float(params.get("take_profit_pct", 0.40)))
    tranche_count = max(int(params.get("tranches", 10)), 1)
    exit_tranche_count = max(int(params.get("exit_tranches", 5)), 1)
    lookback_years = max(int(params.get("lookback_years", 3)), 1)
    code_map = {_to_code(holding): holding for holding in holdings}
    valid_codes = sorted(code for code in code_map if code in data_map and not data_map[code].empty)
    if not valid_codes:
        raise ValueError("No valid codes with data for deep drawdown recovery")

    frames = {code: data_map[code].sort_index() for code in valid_codes}
    all_dates = sorted(set().union(*(frame.index for frame in frames.values())))
    sleeve_cash = {
        code: initial_cash * code_map[code].allocation_pct / 100.0
        for code in valid_codes
    }
    shares = {code: 0.0 for code in valid_codes}
    cost_basis = {code: 0.0 for code in valid_codes}
    previous_close: Dict[str, float | None] = {code: None for code in valid_codes}
    rolling_highs = {code: deque() for code in valid_codes}
    monthly_buys: Dict[str, set[pd.Timestamp]] = {code: set() for code in valid_codes}
    monthly_sells: Dict[str, set[pd.Timestamp]] = {code: set() for code in valid_codes}
    tranche_amount = {code: 0.0 for code in valid_codes}
    buys_completed = {code: 0 for code in valid_codes}
    sells_completed = {code: 0 for code in valid_codes}
    exit_share_amount = {code: 0.0 for code in valid_codes}
    open_buys: Dict[str, List[Dict[str, Any]]] = {code: [] for code in valid_codes}
    trades: List[TradeRecord] = []
    equity_points: List[tuple] = []

    def buy(code: str, ts: pd.Timestamp, amount: float, price: float) -> None:
        amount = min(amount, sleeve_cash[code])
        if amount <= 0 or price <= 0:
            return
        quantity = amount / price
        shares[code] += quantity
        cost_basis[code] += amount
        sleeve_cash[code] -= amount
        buys_completed[code] += 1
        open_buys[code].append({"time": ts, "price": price, "shares": quantity})

    def sell(code: str, ts: pd.Timestamp, quantity: float, price: float) -> None:
        quantity = min(quantity, shares[code])
        remaining = quantity
        while remaining > 1e-10 and open_buys[code]:
            entry = open_buys[code][0]
            sold = min(remaining, entry["shares"])
            pnl = sold * (price - entry["price"])
            trades.append(TradeRecord(
                symbol=code, direction=1,
                entry_price=round(entry["price"], 4), exit_price=round(price, 4),
                entry_time=entry["time"], exit_time=ts,
                size=round(sold, 4), leverage=1.0,
                pnl=round(pnl, 2),
                pnl_pct=round((price / entry["price"] - 1) * 100, 4),
                exit_reason="staged_take_profit_40pct",
                holding_bars=(ts - entry["time"]).days,
                commission=0.0,
            ))
            cost_basis[code] -= sold * entry["price"]
            entry["shares"] -= sold
            remaining -= sold
            if entry["shares"] <= 1e-10:
                open_buys[code].pop(0)
        shares[code] -= quantity - remaining
        sleeve_cash[code] += (quantity - remaining) * price
        sells_completed[code] += 1

        if sells_completed[code] >= exit_tranche_count or shares[code] <= 1e-10:
            shares[code] = 0.0
            cost_basis[code] = 0.0
            open_buys[code] = []
            monthly_buys[code] = set()
            monthly_sells[code] = set()
            buys_completed[code] = 0
            sells_completed[code] = 0
            tranche_amount[code] = 0.0
            exit_share_amount[code] = 0.0

    def schedule_monthly_dates(
        frame: pd.DataFrame, ts: pd.Timestamp, count: int,
    ) -> set[pd.Timestamp]:
        dates: set[pd.Timestamp] = set()
        trading_idx = pd.DatetimeIndex(frame.index)
        for month_start in pd.date_range(
            start=ts + pd.offsets.MonthBegin(1), periods=count, freq="MS",
        ):
            future = trading_idx[trading_idx >= month_start]
            if len(future) > 0:
                dates.add(pd.Timestamp(future[0]))
        return dates

    for raw_ts in all_dates:
        ts = pd.Timestamp(raw_ts)
        for code in valid_codes:
            frame = frames[code]
            if ts not in frame.index:
                continue
            open_price = float(frame.loc[ts, "open"])
            prior = previous_close[code]
            exited = False
            cutoff = ts - pd.DateOffset(years=lookback_years)
            history = rolling_highs[code]
            while history and history[0][0] < cutoff:
                history.popleft()
            rolling_peak = history[0][1] if history else None

            if monthly_sells[code] and ts in monthly_sells[code]:
                final_sale = sells_completed[code] + 1 >= exit_tranche_count
                sell(code, ts, shares[code] if final_sale else exit_share_amount[code], open_price)
                exited = True
            elif not monthly_sells[code] and shares[code] > 0 and prior is not None and cost_basis[code] > 0:
                average_cost = cost_basis[code] / shares[code]
                if prior >= average_cost * (1.0 + take_profit_pct) - 1e-12:
                    monthly_buys[code] = set()
                    exit_share_amount[code] = shares[code] / exit_tranche_count
                    monthly_sells[code] = schedule_monthly_dates(
                        frame, ts, max(exit_tranche_count - 1, 0),
                    )
                    sell(code, ts, exit_share_amount[code], open_price)
                    exited = True

            if not exited and shares[code] == 0 and prior is not None and rolling_peak:
                drawdown = prior / float(rolling_peak) - 1.0
                if drawdown <= -drawdown_threshold + 1e-12:
                    tranche_amount[code] = sleeve_cash[code] / tranche_count
                    buy(code, ts, tranche_amount[code], open_price)
                    monthly_buys[code] = schedule_monthly_dates(
                        frame, ts, max(tranche_count - 1, 0),
                    )
            elif (
                not exited
                and shares[code] > 0
                and buys_completed[code] < tranche_count
                and ts in monthly_buys[code]
            ):
                buy(code, ts, tranche_amount[code], open_price)

            close_price = float(frame.loc[ts, "close"])
            previous_close[code] = close_price
            while history and history[-1][1] <= close_price:
                history.pop()
            history.append((ts, close_price))

        portfolio_value = sum(sleeve_cash.values())
        for code in valid_codes:
            if shares[code] <= 0:
                continue
            if ts in frames[code].index:
                portfolio_value += shares[code] * float(frames[code].loc[ts, "close"])
            else:
                portfolio_value += shares[code] * _last_close(code, frames, ts)
        equity_points.append((ts, portfolio_value))

    last_ts = pd.Timestamp(all_dates[-1])
    for code in valid_codes:
        exit_price = _last_close(code, frames, last_ts)
        for entry in open_buys[code]:
            pnl = entry["shares"] * (exit_price - entry["price"])
            trades.append(TradeRecord(
                symbol=code, direction=1,
                entry_price=round(entry["price"], 4), exit_price=round(exit_price, 4),
                entry_time=entry["time"], exit_time=last_ts,
                size=round(entry["shares"], 4), leverage=1.0,
                pnl=round(pnl, 2),
                pnl_pct=round((exit_price / entry["price"] - 1) * 100, 4),
                exit_reason="end_of_backtest",
                holding_bars=(last_ts - entry["time"]).days,
                commission=0.0,
            ))

    equity_series = pd.Series(
        [equity for _, equity in equity_points],
        index=pd.DatetimeIndex([timestamp for timestamp, _ in equity_points]),
    )
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
