import numpy as np
import pandas as pd
import pytest

from src.paper_trading.comparison_engine import (
    build_defensive_momentum_targets,
    build_spy_ma200_targets,
    simulate_weight_schedule,
    summarize_simulation,
)


def _momentum_fixture():
    index = pd.bdate_range("2023-01-02", periods=320)
    symbols = [f"S{i:02d}.US" for i in range(20)]
    close = pd.DataFrame({
        symbol: np.linspace(20 + i, 45 + i * 2, len(index))
        for i, symbol in enumerate(symbols)
    }, index=index)
    volume = pd.DataFrame({
        symbol: np.full(len(index), 1_000_000 + i * 10_000)
        for i, symbol in enumerate(symbols)
    }, index=index)
    spy = pd.Series(np.linspace(100, 160, len(index)), index=index, name="SPY.US")
    spy.iloc[-5:] = 50.0
    return close, volume, spy


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


def test_defensive_momentum_is_capped_and_respects_spy_regime():
    close, volume, spy = _momentum_fixture()
    targets = build_defensive_momentum_targets(close, volume, spy)

    risk_on = targets.iloc[-2]
    risk_off = targets.iloc[-1]
    assert (risk_on[risk_on > 0] <= 0.08 + 1e-12).all()
    assert (risk_off[risk_off > 0] <= 0.08 + 1e-12).all()
    assert risk_on.sum() == pytest.approx(0.90)
    assert risk_off.sum() == pytest.approx(0.30)
    assert (risk_on > 0).sum() == 15


def test_momentum_signal_does_not_change_when_future_prices_change():
    close, volume, spy = _momentum_fixture()
    first = build_defensive_momentum_targets(close, volume, spy)
    signal_day = first.index[-2]
    changed = close.copy()
    changed.loc[changed.index > signal_day] *= 10

    second = build_defensive_momentum_targets(changed, volume, spy)

    pd.testing.assert_series_equal(first.loc[signal_day], second.loc[signal_day])
