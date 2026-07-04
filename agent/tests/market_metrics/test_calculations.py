from __future__ import annotations

import pytest

from src.market_metrics.calculations import (
    daily_dca_metrics,
    interval_return,
    maximum_drawdown,
    maximum_loss,
)


def test_interval_return_uses_explicit_baseline():
    assert interval_return(100.0, 121.0) == pytest.approx(0.21)


def test_interval_return_rejects_invalid_values():
    assert interval_return(0.0, 121.0) is None
    assert interval_return(100.0, -1.0) is None


def test_daily_dca_loss_is_relative_to_contributions():
    result = daily_dca_metrics([100.0, 50.0, 80.0])

    assert result is not None
    assert result.total_return == pytest.approx(0.1333333333)
    assert result.max_loss == pytest.approx(-0.25)
    assert result.contribution_count == 3


def test_daily_dca_rejects_non_positive_prices():
    assert daily_dca_metrics([100.0, 0.0, 80.0]) is None


def test_maximum_loss_and_drawdown_are_not_synonyms():
    account = [100.0, 150.0, 120.0]
    principal = [100.0, 100.0, 100.0]

    assert maximum_loss(account, principal) == 0.0
    assert maximum_drawdown(account) == pytest.approx(-0.20)


def test_maximum_loss_uses_changing_principal():
    assert maximum_loss([100.0, 140.0, 170.0], [100.0, 150.0, 200.0]) == pytest.approx(-0.15)

