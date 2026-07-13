"""Pure, next-session portfolio simulation for fixed strategy comparisons."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.metrics import calc_metrics
from src.paper_trading.comparison_models import ComparisonMetrics, ComparisonPoint


@dataclass
class SimulationResult:
    equity: pd.Series
    shares: pd.DataFrame
    cash: pd.Series
    stock_exposure: pd.Series
    cash_ratio: pd.Series
    turnover: float
    transaction_cost: float


def build_spy_buy_hold_targets(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"SPY.US": 1.0}, index=index)


def build_spy_ma200_targets(spy_close: pd.Series) -> pd.DataFrame:
    invested = (spy_close > spy_close.rolling(200, min_periods=200).mean()).astype(float)
    return invested.to_frame("SPY.US")


def capped_inverse_vol_weights(
    volatility: pd.Series, gross: float, cap: float,
) -> pd.Series:
    valid = volatility.replace([np.inf, -np.inf], np.nan).dropna()
    valid = valid[valid > 0]
    weights = pd.Series(0.0, index=volatility.index)
    remaining = list(valid.index)
    budget = float(gross)
    while remaining and budget > 1e-12:
        inverse = 1.0 / valid.loc[remaining]
        proposal = inverse / inverse.sum() * budget
        capped = proposal[proposal >= cap]
        if capped.empty:
            weights.loc[proposal.index] = proposal
            break
        weights.loc[capped.index] = cap
        budget -= cap * len(capped)
        capped_names = set(capped.index)
        remaining = [name for name in remaining if name not in capped_names]
    return weights


def build_defensive_momentum_targets(
    close: pd.DataFrame, volume: pd.DataFrame, spy_close: pd.Series,
) -> pd.DataFrame:
    close = close.sort_index().astype(float)
    volume = volume.reindex_like(close).astype(float)
    spy_close = spy_close.reindex(close.index).ffill().astype(float)
    dollar_volume = (close * volume).rolling(60, min_periods=60).mean()
    momentum = close.shift(21) / close.shift(252) - 1.0
    sma200 = close.rolling(200, min_periods=200).mean()
    volatility = close.pct_change().rolling(20, min_periods=20).std()
    spy_sma200 = spy_close.rolling(200, min_periods=200).mean()
    weekly_dates = close.groupby(close.index.to_period("W-FRI")).tail(1).index
    rows: list[pd.Series] = []
    for ts in weekly_dates:
        liquid = dollar_volume.loc[ts].dropna().nlargest(200).index
        eligible_mask = (
            (close.loc[ts, liquid] > 5.0)
            & (close.loc[ts, liquid] > sma200.loc[ts, liquid])
            & momentum.loc[ts, liquid].notna()
        )
        eligible = eligible_mask[eligible_mask].index
        selected = momentum.loc[ts, eligible].nlargest(15).index
        gross = 0.90 if spy_close.loc[ts] > spy_sma200.loc[ts] else 0.30
        selected_weights = capped_inverse_vol_weights(
            volatility.loc[ts, selected], gross, 0.08,
        )
        row = pd.Series(0.0, index=close.columns, name=ts)
        row.loc[selected_weights.index] = selected_weights
        rows.append(row)
    return pd.DataFrame(rows).sort_index()


def _self_financing_targets(
    equity: float, current_value: pd.Series, weights: pd.Series, cost_rate: float,
) -> tuple[pd.Series, float]:
    cost = 0.0
    for _ in range(20):
        target = weights * max(0.0, equity - cost)
        updated = float((target - current_value).abs().sum()) * cost_rate
        if abs(updated - cost) < 1e-9:
            cost = updated
            break
        cost = updated
    return weights * max(0.0, equity - cost), cost


def simulate_weight_schedule(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    targets: pd.DataFrame,
    start_date,
    initial_capital: float,
    cost_bps: float,
) -> SimulationResult:
    index = open_prices.index.intersection(close_prices.index).sort_values()
    symbols = list(open_prices.columns.intersection(close_prices.columns))
    opens = open_prices.reindex(index)[symbols].astype(float)
    closes = close_prices.reindex(index)[symbols].astype(float)
    daily_targets = targets.reindex(index).ffill().fillna(0.0).reindex(columns=symbols, fill_value=0.0)
    execution_targets = daily_targets.shift(1).fillna(0.0)
    active = index[index >= pd.Timestamp(start_date)]
    holdings = pd.Series(0.0, index=symbols)
    cash = float(initial_capital)
    last_target: pd.Series | None = None
    equity_values: list[float] = []
    cash_values: list[float] = []
    share_rows: list[pd.Series] = []
    exposures: list[float] = []
    cash_ratios: list[float] = []
    turnover = 0.0
    total_cost = 0.0
    rate = float(cost_bps) / 10_000.0

    for ts in active:
        open_row = opens.loc[ts]
        close_row = closes.loc[ts]
        valuation_open = open_row.fillna(close_row)
        target = execution_targets.loc[ts].fillna(0.0).clip(lower=0.0)
        if target.sum() > 1.0 + 1e-9:
            raise ValueError("target weights cannot exceed 100%")
        if last_target is None or not target.equals(last_target):
            current_value = holdings * valuation_open
            pretrade_equity = cash + float(current_value.sum())
            target_value, cost = _self_financing_targets(pretrade_equity, current_value, target, rate)
            valid_open = valuation_open.replace(0, np.nan)
            holdings = (target_value / valid_open).fillna(0.0)
            cash = pretrade_equity - float(target_value.sum()) - cost
            turnover += float((target_value - current_value).abs().sum()) / max(pretrade_equity, 1e-12)
            total_cost += cost
            last_target = target.copy()
        stock_value = float((holdings * close_row).sum())
        equity = cash + stock_value
        equity_values.append(equity)
        cash_values.append(cash)
        share_rows.append(holdings.copy())
        exposures.append(stock_value / equity if equity else 0.0)
        cash_ratios.append(cash / equity if equity else 1.0)

    return SimulationResult(
        equity=pd.Series(equity_values, index=active, dtype=float),
        shares=pd.DataFrame(share_rows, index=active, columns=symbols),
        cash=pd.Series(cash_values, index=active, dtype=float),
        stock_exposure=pd.Series(exposures, index=active, dtype=float),
        cash_ratio=pd.Series(cash_ratios, index=active, dtype=float),
        turnover=turnover,
        transaction_cost=total_cost,
    )


def summarize_simulation(
    result: SimulationResult, initial_capital: float,
) -> tuple[ComparisonMetrics, list[ComparisonPoint]]:
    raw = calc_metrics(result.equity, [], initial_capital)
    peak = result.equity.cummax()
    drawdown = result.equity / peak - 1.0
    year_end = result.equity.resample("YE").last()
    year_base = year_end.shift(1)
    if not year_base.empty:
        year_base.iloc[0] = initial_capital
    annual = (year_end / year_base - 1.0).dropna()
    month_end = result.equity.resample("ME").last()
    monthly = month_end.pct_change().dropna()
    metrics = ComparisonMetrics(
        total_return=float(raw["total_return"]),
        cagr=float(raw["annual_return"]),
        sharpe=float(raw["sharpe"]),
        max_drawdown=float(raw["max_drawdown"]),
        calmar=float(raw["calmar"]),
        annual_vol=float(raw["annual_vol"]),
        worst_year=float(annual.min()) if not annual.empty else None,
        monthly_win_rate=float((monthly > 0).mean()) if not monthly.empty else None,
        turnover=float(result.turnover),
        transaction_cost=float(result.transaction_cost),
        average_cash_ratio=float(result.cash_ratio.mean()),
        minimum_cash_ratio=float(result.cash_ratio.min()),
        annual_returns={str(ts.year): float(value) for ts, value in annual.items()},
    )
    points = [
        ComparisonPoint(
            date=ts.date().isoformat(), equity=float(equity),
            normalized=float(equity / initial_capital), drawdown=float(drawdown.loc[ts]),
            stock_exposure=float(result.stock_exposure.loc[ts]),
            cash_ratio=float(result.cash_ratio.loc[ts]),
        )
        for ts, equity in result.equity.items()
    ]
    return metrics, points
