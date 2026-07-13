import pandas as pd
import pytest

from src.paper_trading.comparison_engine import (
    build_spy_ma200_targets,
    simulate_weight_schedule,
    summarize_simulation,
)


def test_close_signal_executes_at_next_open():
    index = pd.bdate_range("2024-01-02", periods=202)
    close = pd.DataFrame({"SPY.US": [100.0] * 200 + [101.0, 102.0]}, index=index)
    open_ = close.copy()
    open_.iloc[-1, 0] = 120.0
    targets = build_spy_ma200_targets(close["SPY.US"])

    result = simulate_weight_schedule(open_, close, targets, index[-1], 100_000, 0)

    assert result.shares.iloc[0]["SPY.US"] == pytest.approx(100_000 / 120.0)


def test_cost_is_self_financing_and_does_not_create_negative_cash():
    index = pd.bdate_range("2024-01-02", periods=3)
    prices = pd.DataFrame({"SPY.US": [100.0, 100.0, 100.0]}, index=index)
    targets = pd.DataFrame({"SPY.US": [1.0, 1.0, 1.0]}, index=index)

    result = simulate_weight_schedule(prices, prices, targets, index[1], 100_000, 20)

    assert result.transaction_cost == pytest.approx(199.6008, rel=1e-4)
    assert result.cash.iloc[0] == pytest.approx(0.0, abs=1e-8)
    assert result.equity.iloc[0] == pytest.approx(99_800.3992, rel=1e-4)


def test_summary_uses_the_same_equity_curve_for_metrics_and_points():
    index = pd.bdate_range("2024-01-02", periods=3)
    prices = pd.DataFrame({"SPY.US": [100.0, 105.0, 110.0]}, index=index)
    targets = pd.DataFrame({"SPY.US": 1.0}, index=index)
    result = simulate_weight_schedule(prices, prices, targets, index[1], 100_000, 0)

    metrics, points = summarize_simulation(result, 100_000)

    assert points[-1].equity == pytest.approx(result.equity.iloc[-1])
    assert metrics.total_return == pytest.approx(result.equity.iloc[-1] / 100_000 - 1)
