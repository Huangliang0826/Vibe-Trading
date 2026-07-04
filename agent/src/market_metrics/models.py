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

