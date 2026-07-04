"""Canonical market-data validation and financial metric calculations."""

from .calculations import (
    DailyDcaMetrics,
    daily_dca_metrics,
    interval_return,
    maximum_drawdown,
    maximum_loss,
)
from .models import (
    DataQuality,
    LatestQuote,
    MarketBar,
    MarketDataStatus,
    MarketMetricsResponse,
    MarketMetricValues,
    PriceObservation,
    QualityIssue,
)
from .validation import validate_bars

FORMULA_VERSION = "market-metrics-v1"

__all__ = [
    "FORMULA_VERSION",
    "DailyDcaMetrics",
    "DataQuality",
    "LatestQuote",
    "MarketBar",
    "MarketDataStatus",
    "MarketMetricsResponse",
    "MarketMetricValues",
    "PriceObservation",
    "QualityIssue",
    "daily_dca_metrics",
    "interval_return",
    "maximum_drawdown",
    "maximum_loss",
    "validate_bars",
]
