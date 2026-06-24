"""Explainable smart T-style swing strategy for trapped positions.

The simulation assumes an investor already owns a core HSTECH ETF position and
uses reserved cash to buy short-term dips, then sells those tactical shares on
rebounds. It is a research backtest, not an execution engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SmartTParams:
    initial_position: float = 0.60
    core_position: float = 0.35
    tranche: float = 0.08
    buy_gap: float = -0.025
    panic_gap: float = -0.06
    sell_rebound: float = 0.035
    cost_take_profit: float = 0.012
    max_trades_per_month: int = 6
    rsi_window: int = 14
    ma_window: int = 20
    vol_window: int = 20


def _to_price_frame(bars: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for bar in bars:
        try:
            close = float(bar.get("close"))
        except (TypeError, ValueError):
            continue
        if not isfinite(close) or close <= 0:
            continue
        date = pd.to_datetime(str(bar.get("date", ""))[:10], errors="coerce")
        if pd.isna(date):
            continue
        rows.append({"date": date, "close": close})
    if not rows:
        return pd.DataFrame(columns=["close"])
    return pd.DataFrame(rows).drop_duplicates("date").set_index("date").sort_index()


def _metrics(equity: pd.Series, periods_per_year: int = 252) -> dict[str, float]:
    if len(equity) < 2:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "annual_vol": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
        }
    total = float(equity.iloc[-1] / equity.iloc[0] - 1)
    ann = float((1 + total) ** (periods_per_year / max(len(equity), 1)) - 1)
    rets = equity.pct_change().fillna(0.0)
    vol = float(rets.std() * sqrt(periods_per_year))
    sharpe = ann / vol if vol > 1e-8 else 0.0
    peak = equity.cummax()
    max_dd = float((equity / peak - 1).min())
    calmar = ann / abs(max_dd) if abs(max_dd) > 1e-8 else 0.0
    return {
        "total_return": round(total, 4),
        "annual_return": round(ann, 4),
        "annual_vol": round(vol, 4),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
        "calmar": round(calmar, 2),
    }


def _curve(series: pd.Series) -> list[list[Any]]:
    return [[idx.strftime("%Y-%m-%d"), round(float(value), 4)] for idx, value in series.items()]


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window, min_periods=window).mean()
    loss = (-delta.clip(upper=0)).rolling(window, min_periods=window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def run_smart_t(
    bars: list[dict[str, Any]],
    *,
    params: SmartTParams | None = None,
) -> dict[str, Any]:
    params = params or SmartTParams()
    prices = _to_price_frame(bars)
    if len(prices) < params.ma_window + params.rsi_window + 30:
        raise ValueError("insufficient price history for smart T")

    close = prices["close"]
    ma = close.rolling(params.ma_window, min_periods=params.ma_window).mean()
    vol = close.pct_change().rolling(params.vol_window, min_periods=params.vol_window).std()
    rsi = _rsi(close, params.rsi_window)

    initial_capital = 1.0
    first_price = float(close.iloc[0])
    shares = params.initial_position / first_price
    cash = initial_capital * (1 - params.initial_position)
    cost_basis = params.initial_position
    realized_profit = 0.0
    tactical_shares = 0.0
    tactical_lots: list[dict[str, float]] = []
    current_month = ""
    month_trades = 0

    equity_vals: list[float] = []
    buy_hold_vals: list[float] = []
    event_rows: list[dict[str, Any]] = []
    current_signal: dict[str, Any] = {
        "action": "观察",
        "reason": "等待低吸或高抛条件",
        "suggested_cash": 0.0,
        "price": first_price,
    }

    for date, raw_price in close.items():
        price = float(raw_price)
        month_key = date.strftime("%Y-%m")
        if month_key != current_month:
            current_month = month_key
            month_trades = 0

        total_value_before = cash + shares * price
        position_ratio = shares * price / max(total_value_before, 1e-9)
        effective_cost = (cost_basis - realized_profit) / shares if shares > 0 else price
        trapped_gap = price / max(effective_cost, 1e-9) - 1
        ma20 = ma.loc[date]
        rsi14 = rsi.loc[date]
        vol20 = vol.loc[date]
        below_ma = pd.notna(ma20) and price < float(ma20) * 0.985
        oversold = pd.notna(rsi14) and float(rsi14) <= 42
        high_vol = pd.notna(vol20) and float(vol20) > 0.035
        can_trade = month_trades < params.max_trades_per_month

        action = "观察"
        reason = "等待低吸或高抛条件"
        trade_cash = 0.0
        trade_shares = 0.0
        pnl = 0.0

        should_buy = (
            can_trade
            and cash > initial_capital * params.tranche * 0.5
            and trapped_gap <= params.buy_gap
            and (below_ma or oversold or trapped_gap <= params.panic_gap)
            and not high_vol
        )
        buy_setup_without_cash = (
            cash <= initial_capital * params.tranche * 0.5
            and trapped_gap <= params.buy_gap
            and (below_ma or oversold or trapped_gap <= params.panic_gap)
        )
        tactical_cost = (
            sum(lot["shares"] * lot["price"] for lot in tactical_lots) / tactical_shares
            if tactical_shares > 0 else 0.0
        )
        should_sell = (
            can_trade
            and tactical_shares > 0
            and position_ratio > params.core_position
            and (
                price >= tactical_cost * (1 + params.sell_rebound)
                or price >= effective_cost * (1 + params.cost_take_profit)
            )
        )

        if should_sell:
            sell_shares = min(
                tactical_shares,
                shares,
                max(0.0, (position_ratio - params.core_position) * total_value_before / price),
            )
            if sell_shares > 0:
                proceeds = sell_shares * price
                remaining_to_sell = sell_shares
                cost_removed = 0.0
                while remaining_to_sell > 1e-12 and tactical_lots:
                    lot = tactical_lots[-1]
                    take = min(remaining_to_sell, lot["shares"])
                    cost_removed += take * lot["price"]
                    lot["shares"] -= take
                    remaining_to_sell -= take
                    if lot["shares"] <= 1e-12:
                        tactical_lots.pop()
                shares -= sell_shares
                tactical_shares -= sell_shares
                cash += proceeds
                cost_basis -= cost_removed
                pnl = proceeds - cost_removed
                realized_profit += pnl
                trade_cash = proceeds
                trade_shares = sell_shares
                month_trades += 1
                action = "高抛止盈"
                reason = "T仓反弹达标，兑现价差"
        elif should_buy:
            buy_cash = min(cash, initial_capital * params.tranche)
            if buy_cash > 0:
                buy_shares = buy_cash / price
                shares += buy_shares
                tactical_shares += buy_shares
                tactical_lots.append({"shares": buy_shares, "price": price})
                cash -= buy_cash
                cost_basis += buy_cash
                trade_cash = buy_cash
                trade_shares = buy_shares
                month_trades += 1
                action = "低吸T仓"
                reason = "价格低于有效成本且短线超跌"
        elif buy_setup_without_cash:
            action = "观察"
            reason = "已满足低吸条件，但预留现金不足"

        total_value = cash + shares * price
        effective_cost = (cost_basis - realized_profit) / shares if shares > 0 else price
        equity_vals.append(total_value / initial_capital)
        buy_hold_vals.append(price / first_price)

        current_signal = {
            "action": action,
            "reason": reason,
            "suggested_cash": round(trade_cash, 4),
            "price": round(price, 4),
            "effective_cost": round(effective_cost, 4),
            "trapped_gap": round(price / max(effective_cost, 1e-9) - 1, 4),
            "position_ratio": round(shares * price / max(total_value, 1e-9), 4),
            "cash_ratio": round(cash / max(total_value, 1e-9), 4),
            "rsi": round(float(rsi14), 2) if pd.notna(rsi14) else None,
        }

        if action != "观察":
            event_rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "action": action,
                "price": round(price, 4),
                "cash": round(trade_cash, 4),
                "shares": round(trade_shares, 6),
                "pnl": round(pnl, 4),
                "effective_cost": round(effective_cost, 4),
                "position_ratio": current_signal["position_ratio"],
                "reason": reason,
            })

    equity = pd.Series(equity_vals, index=close.index)
    buy_hold = pd.Series(buy_hold_vals, index=close.index)
    final_price = float(close.iloc[-1])
    final_value = cash + shares * final_price
    initial_effective_cost = first_price
    final_effective_cost = (cost_basis - realized_profit) / shares if shares > 0 else final_price
    sells = [e for e in event_rows if e["action"] == "高抛止盈"]
    winning = [e for e in sells if e["pnl"] > 0]

    return {
        "params": {
            "initial_position": params.initial_position,
            "core_position": params.core_position,
            "tranche": params.tranche,
            "buy_gap": params.buy_gap,
            "sell_rebound": params.sell_rebound,
            "cost_take_profit": params.cost_take_profit,
            "max_trades_per_month": params.max_trades_per_month,
        },
        "current_signal": current_signal,
        "summary": {
            "final_value": round(final_value, 4),
            "cash": round(cash, 4),
            "shares": round(shares, 6),
            "realized_profit": round(realized_profit, 4),
            "effective_cost": round(final_effective_cost, 4),
            "cost_reduction": round(final_effective_cost / initial_effective_cost - 1, 4),
            "trade_count": len(event_rows),
            "sell_count": len(sells),
            "win_rate": round(len(winning) / len(sells), 4) if sells else 0.0,
        },
        "metrics": {
            "smart_t": _metrics(equity),
            "buy_and_hold": _metrics(buy_hold),
        },
        "smart_t": {"label": "智能做T", "equity": _curve(equity)},
        "buy_and_hold": {"label": "买入持有", "equity": _curve(buy_hold)},
        "events": event_rows[-120:],
    }
