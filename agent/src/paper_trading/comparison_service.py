"""Data loading and orchestration for fixed paper-strategy comparisons."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from src.paper_trading.comparison_engine import (
    build_defensive_momentum_targets,
    build_spy_buy_hold_targets,
    build_spy_ma200_targets,
    simulate_weight_schedule,
    summarize_simulation,
)
from src.paper_trading.comparison_models import (
    ComparisonStatus,
    ScorecardItem,
    StrategyResult,
)
from src.paper_trading.comparison_storage import StrategyComparisonStore


def _default_universe_loader(universe: str, period: str):
    from src.tools.alpha_bench_tool import _load_universe_panel
    return _load_universe_panel(universe, period)


def _default_spy_loader(start: str, end: str) -> pd.DataFrame:
    from backtest.loaders.registry import resolve_loader
    fetched = resolve_loader("us_equity").fetch(["SPY.US"], start, end)
    frame = fetched.get("SPY.US")
    if frame is None or frame.empty:
        raise RuntimeError("SPY data unavailable")
    return frame


def _result(key: str, label: str, simulation, initial: float, coverage: float) -> StrategyResult:
    metrics, points = summarize_simulation(simulation, initial)
    return StrategyResult(
        key=key, label=label, status="completed", metrics=metrics,
        points=points, coverage_rate=coverage,
    )


def _scorecard(momentum: StrategyResult, timing: StrategyResult) -> list[ScorecardItem]:
    if momentum.metrics is None or timing.metrics is None:
        return [ScorecardItem(
            key="formal_validation", label="正式验证", status="unknown",
            detail="Strategy V0 数据不可用，无法判断。",
        )]
    checks = [
        ("max_drawdown", "最大回撤不超过 12%", momentum.metrics.max_drawdown >= -0.12),
        ("sharpe", "Sharpe 不低于 0.8", momentum.metrics.sharpe >= 0.8),
        ("positive_after_cost", "扣除成本后收益为正", momentum.metrics.total_return > 0),
        ("risk_adjusted_vs_timing", "风险调整收益超过 SPY / 现金轮动", momentum.metrics.calmar > timing.metrics.calmar),
    ]
    items = [ScorecardItem(
        key=key, label=label, status="preliminary" if passed else "fail",
        detail="初步通过（当前成分股样本）" if passed else "未通过",
    ) for key, label, passed in checks]
    items.append(ScorecardItem(
        key="formal_validation", label="正式验证", status="unknown",
        detail="当前 S&P 500 成分股存在幸存者偏差，不能产生正式 PASS。",
    ))
    return items


def run_strategy_comparison(
    run_id: str,
    store: StrategyComparisonStore,
    *,
    universe_loader: Callable = _default_universe_loader,
    spy_loader: Callable = _default_spy_loader,
):
    run = store.get(run_id)
    if run is None:
        raise ValueError("comparison run not found")
    run.status = ComparisonStatus.running
    run.error = None
    store.save(run)
    request = run.request
    start = pd.Timestamp(request.start_date)
    end = pd.Timestamp(request.end_date)
    fetch_start = (start - pd.DateOffset(days=500)).date().isoformat()
    end_text = end.date().isoformat()

    try:
        spy = spy_loader(fetch_start, end_text).sort_index()
        spy.index = pd.to_datetime(spy.index).tz_localize(None)
        spy = spy.loc[spy.index <= end]
        if not {"open", "close"}.issubset(spy.columns) or spy.loc[spy.index >= start].empty:
            raise RuntimeError("SPY data unavailable for requested window")
        spy_open = spy[["open"]].rename(columns={"open": "SPY.US"})
        spy_close = spy[["close"]].rename(columns={"close": "SPY.US"})
        coverage = float(spy_close.loc[spy_close.index >= start].notna().mean().iloc[0])
        buy_hold = _result(
            "spy_buy_hold", "SPY 买入持有",
            simulate_weight_schedule(
                spy_open, spy_close, build_spy_buy_hold_targets(spy.index),
                start, request.initial_capital, request.cost_bps,
            ), request.initial_capital, coverage,
        )
        timing = _result(
            "spy_ma200", "SPY / 现金 200 日均线轮动",
            simulate_weight_schedule(
                spy_open, spy_close, build_spy_ma200_targets(spy_close["SPY.US"]),
                start, request.initial_capital, request.cost_bps,
            ), request.initial_capital, coverage,
        )
    except Exception as exc:
        run.status = ComparisonStatus.failed
        run.error = str(exc)
        run.results = []
        return store.save(run)

    run.results = [buy_hold, timing]
    run.data_through = spy_close.index[-1].date().isoformat()
    run.warnings = [
        "现金收益率按 0% 计算。",
        "所有收盘信号均在下一交易日开盘执行。",
        "Strategy V0 使用当前 S&P 500 成分股，存在幸存者偏差。",
    ]
    try:
        period = f"{fetch_start}/{end_text}"
        panel = universe_loader("sp500", period)
        open_panel = panel["open"].copy()
        close_panel = panel["close"].copy()
        volume_panel = panel["volume"].copy()
        common = open_panel.index.intersection(close_panel.index).intersection(volume_panel.index)
        open_panel = open_panel.reindex(common)
        close_panel = close_panel.reindex(common)
        volume_panel = volume_panel.reindex(common)
        momentum_targets = build_defensive_momentum_targets(
            close_panel, volume_panel, spy_close["SPY.US"],
        )
        stock_coverage = float(close_panel.loc[close_panel.index >= start].notna().mean().mean())
        momentum = _result(
            "defensive_momentum_v0", "防守型个股动量 Strategy V0",
            simulate_weight_schedule(
                open_panel, close_panel, momentum_targets,
                start, request.initial_capital, request.cost_bps,
            ), request.initial_capital, stock_coverage,
        )
        run.results.append(momentum)
        run.status = ComparisonStatus.completed
        run.scorecard = _scorecard(momentum, timing)
    except Exception as exc:
        momentum = StrategyResult(
            key="defensive_momentum_v0", label="防守型个股动量 Strategy V0",
            status="unavailable", error=str(exc), coverage_rate=0,
        )
        run.results.append(momentum)
        run.status = ComparisonStatus.partial
        run.scorecard = _scorecard(momentum, timing)
    return store.save(run)
