"""Typed values shared by the market-metrics package."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class MarketBar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    blocking: bool
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class DataQuality:
    status: Literal["valid", "warning", "invalid"]
    issues: tuple[QualityIssue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class LatestQuote:
    price: float
    prev_close: float
    timestamp: str
    adjustment: Literal["raw", "adjusted"] = "raw"


@dataclass(frozen=True)
class PriceObservation:
    date: str
    value: float
    source: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PriceObservation:
        return cls(str(value["date"]), float(value["value"]), str(value["source"]))


@dataclass(frozen=True)
class MarketMetricValues:
    interval_return_pct: float | None = None
    dca_return_pct: float | None = None
    dca_max_loss_pct: float | None = None
    dca_contribution_count: int | None = None
    buy_hold_max_loss_pct: float | None = None
    max_drawdown_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MarketMetricValues:
        return cls(**{key: value.get(key) for key in cls.__dataclass_fields__})


@dataclass(frozen=True)
class MarketDataStatus:
    quality: Literal["valid", "warning", "invalid"]
    source: str
    data_through: str | None
    issues: tuple[QualityIssue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality,
            "source": self.source,
            "data_through": self.data_through,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MarketDataStatus:
        return cls(
            quality=value["quality"],
            source=str(value["source"]),
            data_through=value.get("data_through"),
            issues=tuple(QualityIssue(**issue) for issue in value.get("issues", [])),
        )


@dataclass(frozen=True)
class MarketMetricsResponse:
    symbol: str
    market: str
    currency: str
    period: str
    adjustment: str
    formula_version: str
    bars: tuple[MarketBar, ...]
    metrics: MarketMetricValues
    baseline: PriceObservation | None
    endpoint: PriceObservation | None
    metric_reasons: dict[str, str]
    data_status: MarketDataStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "currency": self.currency,
            "period": self.period,
            "adjustment": self.adjustment,
            "formula_version": self.formula_version,
            "bars": [bar.to_dict() for bar in self.bars],
            "metrics": self.metrics.to_dict(),
            "baseline": asdict(self.baseline) if self.baseline else None,
            "endpoint": asdict(self.endpoint) if self.endpoint else None,
            "metric_reasons": self.metric_reasons,
            "data_status": self.data_status.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MarketMetricsResponse:
        return cls(
            symbol=str(value["symbol"]),
            market=str(value["market"]),
            currency=str(value["currency"]),
            period=str(value["period"]),
            adjustment=str(value["adjustment"]),
            formula_version=str(value["formula_version"]),
            bars=tuple(MarketBar(**bar) for bar in value.get("bars", [])),
            metrics=MarketMetricValues.from_dict(value.get("metrics", {})),
            baseline=PriceObservation.from_dict(value["baseline"]) if value.get("baseline") else None,
            endpoint=PriceObservation.from_dict(value["endpoint"]) if value.get("endpoint") else None,
            metric_reasons=dict(value.get("metric_reasons", {})),
            data_status=MarketDataStatus.from_dict(value["data_status"]),
        )
