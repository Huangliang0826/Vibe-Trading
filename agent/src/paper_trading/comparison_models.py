"""Contracts for fixed-strategy paper trading comparisons."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

STRATEGY_COMPARISON_VERSION = "paper-comparison.v1"
UNIVERSE_SOURCE_DATE = "2026-05-17"


class ComparisonStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    partial = "partial"
    failed = "failed"


class StrategyComparisonCreate(BaseModel):
    start_date: date
    end_date: date
    initial_capital: float = Field(default=100_000, gt=0)
    cost_bps: float = Field(default=20, ge=0, le=500)

    @model_validator(mode="after")
    def validate_window(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if (self.end_date - self.start_date).days < 365:
            raise ValueError("comparison window must be at least one year")
        return self


class ComparisonPoint(BaseModel):
    date: str
    equity: float
    normalized: float
    drawdown: float
    stock_exposure: float
    cash_ratio: float


class ComparisonMetrics(BaseModel):
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    calmar: float
    annual_vol: float
    worst_year: float | None
    monthly_win_rate: float | None
    turnover: float
    transaction_cost: float
    average_cash_ratio: float
    minimum_cash_ratio: float
    annual_returns: dict[str, float] = Field(default_factory=dict)


class StrategyResult(BaseModel):
    key: Literal["spy_buy_hold", "spy_ma200", "defensive_momentum_v0"]
    label: str
    status: Literal["completed", "unavailable"]
    metrics: ComparisonMetrics | None = None
    points: list[ComparisonPoint] = Field(default_factory=list)
    error: str | None = None
    coverage_rate: float = 0


class ScorecardItem(BaseModel):
    key: str
    label: str
    status: Literal["pass", "fail", "unknown", "preliminary"]
    detail: str


class StrategyComparisonRun(BaseModel):
    run_id: str
    status: ComparisonStatus = ComparisonStatus.queued
    request: StrategyComparisonCreate
    created_at: str
    updated_at: str
    cache_key: str
    cache_hit: bool = False
    calculation_version: str = STRATEGY_COMPARISON_VERSION
    survivorship_bias: bool = True
    universe_source_date: str = UNIVERSE_SOURCE_DATE
    data_through: str | None = None
    results: list[StrategyResult] = Field(default_factory=list)
    scorecard: list[ScorecardItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
