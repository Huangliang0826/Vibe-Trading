from __future__ import annotations

from datetime import date

import pytest

from src.market_metrics.models import LatestQuote, MarketBar
from src.market_metrics.service import build_market_metrics_response


def _bar(day: str, close: float, volume: float | None = 1_000) -> MarketBar:
    return MarketBar(day, close, close, close, close, volume)


def _fixture_bars() -> list[MarketBar]:
    return [
        _bar("2025-01-02", 100.0),
        _bar("2025-01-03", 110.0),
        _bar("2025-01-06", 121.0),
    ]


def _build(**overrides):
    params = {
        "symbol": "AAPL",
        "market": "us",
        "currency": "USD",
        "period": "1Y",
        "requested_start": date(2025, 1, 3),
        "bars": _fixture_bars(),
        "source": "fixture",
    }
    params.update(overrides)
    return build_market_metrics_response(**params)


def test_one_year_uses_pre_range_bar_but_dca_starts_inside_range():
    response = _build()

    assert response.baseline is not None
    assert response.baseline.date == "2025-01-02"
    assert response.metrics.interval_return_pct == pytest.approx(21.0)
    assert response.metrics.dca_return_pct == pytest.approx(5.0)
    assert response.metrics.dca_contribution_count == 2


def test_missing_baseline_returns_null_with_reason():
    response = _build(bars=_fixture_bars()[1:])

    assert response.metrics.interval_return_pct is None
    assert response.metric_reasons["interval_return_pct"] == "missing_baseline"


def test_incompatible_live_quote_is_not_mixed_with_adjusted_history():
    response = _build(quote=LatestQuote(
        price=130.0,
        prev_close=129.0,
        timestamp="2025-01-06T20:00:00Z",
        adjustment="raw",
    ))

    assert response.endpoint is not None
    assert response.endpoint.value == 121.0
    assert response.endpoint.source == "adjusted_history"


def test_invalid_bars_block_metrics_and_preserve_quality_reason():
    response = _build(bars=[
        MarketBar("2025-01-02", 100.0, 90.0, 99.0, 100.0, 1_000),
        _bar("2025-01-03", 110.0),
    ])

    assert response.data_status.quality == "invalid"
    assert response.metrics.interval_return_pct is None
    assert response.metric_reasons["interval_return_pct"] == "invalid_data"


def test_all_period_uses_first_bar_as_baseline_and_investment_day():
    response = _build(period="ALL", requested_start=None)

    assert response.baseline is not None
    assert response.baseline.date == "2025-01-02"
    assert response.metrics.dca_contribution_count == 3

