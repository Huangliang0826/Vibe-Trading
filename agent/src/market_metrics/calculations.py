"""Pure financial arithmetic for charts and portfolio reporting."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class DailyDcaMetrics:
    total_return: float
    max_loss: float
    contribution_count: int


def interval_return(baseline: float, endpoint: float) -> float | None:
    if not isfinite(baseline) or not isfinite(endpoint) or baseline <= 0 or endpoint <= 0:
        return None
    return endpoint / baseline - 1.0


def maximum_loss(values: Sequence[float], principals: Sequence[float]) -> float | None:
    if not values or len(values) != len(principals):
        return None
    returns = [
        value / principal - 1.0
        for value, principal in zip(values, principals)
        if isfinite(value) and isfinite(principal) and principal > 0
    ]
    return min(returns) if returns else None


def maximum_drawdown(values: Sequence[float]) -> float | None:
    if not values or any(not isfinite(value) or value <= 0 for value in values):
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return worst


def daily_dca_metrics(prices: Sequence[float]) -> DailyDcaMetrics | None:
    if len(prices) < 2 or any(not isfinite(price) or price <= 0 for price in prices):
        return None

    units = 0.0
    values: list[float] = []
    principals: list[float] = []
    for index, price in enumerate(prices, start=1):
        units += 1.0 / price
        values.append(units * price)
        principals.append(float(index))

    loss = maximum_loss(values, principals)
    if loss is None:
        return None
    return DailyDcaMetrics(
        total_return=values[-1] / principals[-1] - 1.0,
        max_loss=loss,
        contribution_count=len(prices),
    )

