"""Baseline-aware assembly of chart data and canonical metrics."""
from __future__ import annotations

from datetime import date
from typing import Sequence

from . import FORMULA_VERSION
from .calculations import daily_dca_metrics, interval_return, maximum_drawdown, maximum_loss
from .models import (
    LatestQuote,
    MarketBar,
    MarketDataStatus,
    MarketMetricsResponse,
    MarketMetricValues,
    PriceObservation,
)
from .validation import validate_bars


_METRIC_FIELDS = (
    "interval_return_pct",
    "dca_return_pct",
    "dca_max_loss_pct",
    "buy_hold_max_loss_pct",
    "max_drawdown_pct",
)


def _pct(value: float | None) -> float | None:
    return round(value * 100.0, 10) if value is not None else None


def _empty_metrics(reason: str) -> tuple[MarketMetricValues, dict[str, str]]:
    return MarketMetricValues(), {field: reason for field in _METRIC_FIELDS}


def build_market_metrics_response(
    *,
    symbol: str,
    market: str,
    currency: str,
    period: str,
    requested_start: date | None,
    bars: Sequence[MarketBar],
    source: str,
    quote: LatestQuote | None = None,
) -> MarketMetricsResponse:
    canonical = tuple(bars)
    quality = validate_bars(canonical)
    status = MarketDataStatus(
        quality=quality.status,
        source=source,
        data_through=canonical[-1].timestamp if canonical else None,
        issues=quality.issues,
    )

    if quality.status == "invalid" or not canonical:
        metrics, reasons = _empty_metrics("invalid_data" if canonical else "no_data")
        return MarketMetricsResponse(
            symbol, market, currency, period, "adjusted", FORMULA_VERSION,
            canonical, metrics, None, None, reasons, status,
        )

    if period == "ALL" or requested_start is None:
        baseline_bar = canonical[0]
        investment_bars = canonical
    else:
        prior = [bar for bar in canonical if bar.timestamp[:10] < requested_start.isoformat()]
        investment_bars = tuple(
            bar for bar in canonical if bar.timestamp[:10] >= requested_start.isoformat()
        )
        baseline_bar = prior[-1] if prior else None

    if period == "1D" and quote and quote.adjustment == "adjusted" and quote.prev_close > 0:
        baseline = PriceObservation(quote.timestamp, quote.prev_close, "official_previous_close")
        endpoint = PriceObservation(quote.timestamp, quote.price, "adjusted_quote")
    else:
        baseline = (
            PriceObservation(baseline_bar.timestamp, baseline_bar.close, "adjusted_history")
            if baseline_bar else None
        )
        endpoint_bar = canonical[-1]
        endpoint = PriceObservation(endpoint_bar.timestamp, endpoint_bar.close, "adjusted_history")

    if baseline is None:
        metrics, reasons = _empty_metrics("missing_baseline")
        return MarketMetricsResponse(
            symbol, market, currency, period, "adjusted", FORMULA_VERSION,
            canonical, metrics, None, endpoint, reasons, status,
        )

    prices = [bar.close for bar in investment_bars]
    dca = daily_dca_metrics(prices) if len(prices) >= 2 else None
    buy_hold_path = [baseline.value, *prices]
    fixed_principal = [baseline.value] * len(buy_hold_path)
    interval = interval_return(baseline.value, endpoint.value)
    metrics = MarketMetricValues(
        interval_return_pct=_pct(interval),
        dca_return_pct=_pct(dca.total_return) if dca else None,
        dca_max_loss_pct=_pct(dca.max_loss) if dca else None,
        dca_contribution_count=dca.contribution_count if dca else None,
        buy_hold_max_loss_pct=_pct(maximum_loss(buy_hold_path, fixed_principal)),
        max_drawdown_pct=_pct(maximum_drawdown(buy_hold_path)),
    )
    reasons: dict[str, str] = {}
    if dca is None:
        reasons.update({
            "dca_return_pct": "insufficient_observations",
            "dca_max_loss_pct": "insufficient_observations",
        })
    return MarketMetricsResponse(
        symbol, market, currency, period, "adjusted", FORMULA_VERSION,
        canonical, metrics, baseline, endpoint, reasons, status,
    )
