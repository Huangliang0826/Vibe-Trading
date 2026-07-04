from __future__ import annotations

import pandas as pd
import pytest

from backtest.metrics import calc_metrics


def test_external_contributions_change_max_loss_denominator():
    dates = pd.bdate_range("2026-01-01", periods=3)
    equity = pd.Series([100.0, 140.0, 170.0], index=dates)
    principal = pd.Series([100.0, 150.0, 200.0], index=dates)

    metrics = calc_metrics(
        equity,
        [],
        100.0,
        invested_principal=principal,
    )

    assert metrics["max_loss"] == pytest.approx(-0.15)
    assert metrics["max_drawdown"] == 0.0


def test_fixed_capital_loss_and_drawdown_remain_distinct():
    dates = pd.bdate_range("2026-01-01", periods=3)
    equity = pd.Series([100.0, 150.0, 120.0], index=dates)

    metrics = calc_metrics(equity, [], 100.0)

    assert metrics["max_loss"] == 0.0
    assert metrics["max_drawdown"] == pytest.approx(-0.20)

