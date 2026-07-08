"""No-lookahead strategy context for opportunity scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd

from backtest.engines.base import _align
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.loaders.yfinance_loader import DataLoader as YFinanceLoader
from backtest.metrics import calc_metrics
from backtest.models import TradeRecord
from src.opportunity_center.models import StrategyAction, StrategyContext
from src.paper_trading.executor import _run_dca, _smart_dca_multiplier, evaluate_strategy
from src.paper_trading.hstech_best import (
    STRATEGY_LABELS,
    STRATEGY_NAMES,
    normalize_best_strategy_symbol,
    strategy_params,
    strategy_sort_key,
)
from src.paper_trading.models import PaperHolding
from src.paper_trading.strategies import _to_code, generate_dca, generate_signals

_DCA_FREQ_MAP = {
    "weekly": "W-MON",
    "biweekly": "2W-MON",
    "monthly": "MS",
}
_INITIAL_CASH = 100_000.0
_ACTION_TOLERANCE = 1e-9

# Strategies whose real behaviour (tranche deployment / drawdown-triggered
# accumulation and profit-taking) is simulated bar-by-bar in the executor
# rather than expressible as a plain target-weight signal. ``generate_signals``
# does not handle them, so we route their metrics through the executor's
# ``evaluate_strategy`` core and approximate the action signal with a deployment
# ramp — mirroring how ``dca``/``smart_dca`` take metrics from ``_run_dca`` while
# their action signal comes from a ramp.
_EXECUTOR_SIMULATED = {
    "dca_then_hold",
    "dca_two_year_then_hold",
    "dca_one_year_then_hold",
    "accelerated_dca_entry",
    "deep_drawdown_recovery",
}

# Number of monthly tranches over which each executor-simulated strategy ramps
# to full allocation, used only to build the approximate action signal.
_DEPLOY_RAMP_STEPS = {
    "dca_then_hold": 36,
    "dca_two_year_then_hold": 24,
    "dca_one_year_then_hold": 12,
    "accelerated_dca_entry": 12,
    # deep_drawdown_recovery deploys on drawdowns and takes profit on the way
    # up, so no fixed window fits; a one-year ramp is a coarse action proxy.
    "deep_drawdown_recovery": 12,
}


@dataclass(frozen=True)
class StrategyEvaluation:
    selected_strategy: str
    strategy_label: str
    action: StrategyAction
    signal_date: str
    current_weight: float
    oos_total_return: float
    oos_max_drawdown: float
    oos_sharpe: float
    params: dict[str, object]
    data_as_of: str

    def as_context(self) -> StrategyContext:
        return StrategyContext(
            strategy_name=self.selected_strategy,
            strategy_label=self.strategy_label,
            action=self.action,
            signal_date=self.signal_date,
            current_weight=self.current_weight,
            oos_total_return=self.oos_total_return,
            oos_max_drawdown=self.oos_max_drawdown,
            oos_sharpe=self.oos_sharpe,
            params=dict(self.params),
            data_as_of=self.data_as_of,
        )


def evaluate_strategy_context(
    market: str,
    code: str,
    as_of: date,
    start_date: str = "2020-01-01",
) -> StrategyContext:
    holding, loader_code = _build_holding(market, code)
    frame = _load_price_history(loader_code, start_date=start_date, as_of=as_of)
    return evaluate_frame(frame, holding=holding, as_of=as_of).as_context()


def evaluate_frame(
    frame: pd.DataFrame,
    holding: PaperHolding,
    as_of: date,
    strategy_names: Iterable[str] | None = None,
) -> StrategyEvaluation:
    trimmed = _trim_frame(frame, as_of)
    if len(trimmed) < 504:
        raise ValueError("Strategy context requires at least 504 trading rows")

    training = trimmed.iloc[:-252].copy()
    oos = trimmed.iloc[-252:].copy()
    candidate_names = tuple(strategy_names or STRATEGY_NAMES)

    runs: list[dict[str, object]] = []
    for strategy_name in candidate_names:
        params = strategy_params(strategy_name)
        metrics = _metrics_for_strategy(training, holding, strategy_name, params)
        runs.append({
            "strategy": {
                "name": strategy_name,
                "label": STRATEGY_LABELS.get(strategy_name, strategy_name),
                "params": params,
            },
            "metrics": metrics,
        })

    if not runs:
        raise ValueError("No strategies available for evaluation")

    best = sorted(runs, key=strategy_sort_key)[0]
    selected_strategy = str(best["strategy"]["name"])
    params = dict(best["strategy"]["params"])
    full_signal = _strategy_signal_series(selected_strategy, trimmed, holding, params)
    equity_curve, trades = _backtest_strategy(trimmed, holding, selected_strategy, params)
    oos_metrics = _oos_metrics(equity_curve, trades, oos.index)

    previous_weight = float(full_signal.iloc[-2]) if len(full_signal) > 1 else 0.0
    current_weight = float(full_signal.iloc[-1]) if len(full_signal) else 0.0

    return StrategyEvaluation(
        selected_strategy=selected_strategy,
        strategy_label=str(best["strategy"]["label"]),
        action=_classify_action(previous_weight, current_weight),
        signal_date=trimmed.index[-1].date().isoformat(),
        current_weight=round(current_weight * 100.0, 4),
        oos_total_return=float(oos_metrics.get("total_return") or 0.0),
        oos_max_drawdown=float(oos_metrics.get("max_drawdown") or 0.0),
        oos_sharpe=float(oos_metrics.get("sharpe") or 0.0),
        params=params,
        data_as_of=as_of.isoformat(),
    )


def _build_holding(market: str, code: str) -> tuple[PaperHolding, str]:
    paper_symbol, loader_code, _display_code = normalize_best_strategy_symbol(code, market)
    return PaperHolding(symbol=paper_symbol, market=market, allocation_pct=100.0), loader_code


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
        raise ValueError("No price data available on or before as_of")
    return trimmed


def _strategy_signal_series(
    strategy_name: str,
    frame: pd.DataFrame,
    holding: PaperHolding,
    params: dict[str, object],
) -> pd.Series:
    code = _to_code(holding)
    data_map = {code: frame}
    if strategy_name == "smart_dca":
        return _generate_smart_dca_weights(holding, frame, params)
    if strategy_name == "dca":
        return generate_dca([holding], data_map, params)[code]
    if strategy_name in _EXECUTOR_SIMULATED:
        return _generate_deploy_ramp_weights(holding, frame, strategy_name)
    return generate_signals([holding], data_map, strategy_name, params)[code]


def _generate_deploy_ramp_weights(
    holding: PaperHolding,
    frame: pd.DataFrame,
    strategy_name: str,
) -> pd.Series:
    """Monotone ramp to full allocation over the strategy's deployment window.

    Used only for the action signal of executor-simulated strategies (their
    equity/metrics come from ``evaluate_strategy``). Weight climbs one equal step
    per month until fully deployed, then holds — so the action reads as ``buy``
    while accumulating and ``hold`` once fully invested.
    """
    steps_to_full = max(int(_DEPLOY_RAMP_STEPS.get(strategy_name, 12)), 1)
    target_weight = holding.allocation_pct / 100.0
    step = target_weight / steps_to_full
    weights = pd.Series(0.0, index=frame.index, dtype=float)
    ramp_dates = pd.date_range(start=frame.index[0], periods=steps_to_full, freq="MS")
    current_weight = 0.0
    for ramp_date in ramp_dates:
        current_weight = min(current_weight + step, target_weight)
        weights.loc[weights.index >= ramp_date] = current_weight
    return weights


def _generate_smart_dca_weights(
    holding: PaperHolding,
    frame: pd.DataFrame,
    params: dict[str, object],
) -> pd.Series:
    frequency = str(params.get("frequency", "monthly"))
    freq = _DCA_FREQ_MAP.get(frequency, "MS")
    steps_to_full = max(int(params.get("steps_to_full", 12)), 1)
    target_weight = holding.allocation_pct / 100.0
    step = target_weight / steps_to_full
    weights = pd.Series(0.0, index=frame.index, dtype=float)
    dca_dates = pd.date_range(start=frame.index[0], end=frame.index[-1], freq=freq)
    current_weight = 0.0
    for dca_date in dca_dates:
        future = frame.index[frame.index >= dca_date]
        if future.empty:
            continue
        ts = future[0]
        multiplier = _smart_dca_multiplier(frame, ts, params)
        current_weight = min(current_weight + step * multiplier, target_weight)
        weights.loc[weights.index >= ts] = current_weight
    return weights


def _metrics_for_strategy(
    frame: pd.DataFrame,
    holding: PaperHolding,
    strategy_name: str,
    params: dict[str, object],
) -> dict[str, float]:
    equity_curve, trades = _backtest_strategy(frame, holding, strategy_name, params)
    metrics = calc_metrics(equity_curve, trades, _INITIAL_CASH, bars_per_year=None)
    return {
        "total_return": float(metrics.get("total_return") or 0.0),
        "sharpe": float(metrics.get("sharpe") or 0.0),
        "max_drawdown": float(metrics.get("max_drawdown") or 0.0),
    }


def _backtest_strategy(
    frame: pd.DataFrame,
    holding: PaperHolding,
    strategy_name: str,
    params: dict[str, object],
) -> tuple[pd.Series, list[TradeRecord]]:
    code = _to_code(holding)
    data_map = {code: frame}
    if strategy_name in {"dca", "smart_dca"}:
        equity_curve, trades = _run_dca(
            _INITIAL_CASH,
            [holding],
            data_map,
            params,
            smart=strategy_name == "smart_dca",
        )
        return equity_curve.astype(float), trades
    if strategy_name in _EXECUTOR_SIMULATED:
        equity_curve, trades = evaluate_strategy(
            [holding], data_map, strategy_name, params, _INITIAL_CASH,
        )
        return equity_curve.astype(float), trades
    signal = _strategy_signal_series(strategy_name, frame, holding, params)
    return _backtest_signal(frame, holding, signal)


def _backtest_signal(
    frame: pd.DataFrame,
    holding: PaperHolding,
    signal: pd.Series,
) -> tuple[pd.Series, list[TradeRecord]]:
    code = _to_code(holding)
    data_map = {code: frame}
    signal_map = {code: signal.reindex(frame.index).ffill().fillna(0.0).astype(float)}
    dates, close_df, target_pos, _ret_df = _align(data_map, signal_map, [code])
    engine = GlobalEquityEngine({"initial_cash": _INITIAL_CASH}, market=holding.market)
    engine._execute_bars(dates, data_map, close_df, target_pos, [code])
    if not engine.equity_snapshots:
        raise ValueError("Signal backtest produced no equity snapshots")
    equity_curve = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots],
        index=[snapshot.timestamp for snapshot in engine.equity_snapshots],
        dtype=float,
    )
    return equity_curve, engine.trades


def _oos_metrics(
    equity_curve: pd.Series,
    trades: list[TradeRecord],
    oos_index: pd.DatetimeIndex,
) -> dict[str, object]:
    oos_equity = equity_curve.reindex(oos_index).dropna()
    if oos_equity.empty:
        raise ValueError("OOS evaluation produced no equity curve")
    prior = equity_curve.loc[equity_curve.index < oos_index[0]]
    if prior.empty:
        raise ValueError("OOS evaluation requires a pre-window equity boundary")

    boundary = prior.iloc[[-1]]
    metric_equity = pd.concat([boundary, oos_equity])
    initial_cash = float(boundary.iloc[0])
    oos_start, oos_end = oos_equity.index[0], oos_equity.index[-1]
    oos_trades = [
        trade
        for trade in trades
        if oos_start <= _naive_timestamp(trade.entry_time)
        and _naive_timestamp(trade.exit_time) <= oos_end
    ]
    return calc_metrics(metric_equity, oos_trades, initial_cash, bars_per_year=None)


def _naive_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize(None)


def _classify_action(previous_weight: float, current_weight: float) -> StrategyAction:
    prev = max(previous_weight, 0.0)
    curr = max(current_weight, 0.0)
    if prev <= _ACTION_TOLERANCE and curr > _ACTION_TOLERANCE:
        return "entry"
    if prev > _ACTION_TOLERANCE and curr <= _ACTION_TOLERANCE:
        return "exit"
    if curr > prev + _ACTION_TOLERANCE:
        return "add"
    if curr < prev - _ACTION_TOLERANCE:
        return "risk_exit"
    if curr > _ACTION_TOLERANCE:
        return "hold"
    return "wait"
