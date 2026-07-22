"""Contracts for manual allocation backtests and virtual portfolio tracking."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ManualAllocation(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    market: Literal["us", "hk", "cn", "cash"]
    name: str = Field(default="", max_length=100)
    asset_type: Literal["stock", "fund", "bond", "cash"]
    weight: float = Field(..., ge=0, le=1)


class PortfolioDefinition(BaseModel):
    allocations: list[ManualAllocation] = Field(..., min_length=2, max_length=21)
    initial_capital: float = Field(default=100_000.0, gt=0, le=100_000_000)
    installments: int = Field(default=10, ge=1, le=52)
    interval_days: int = Field(default=7, ge=1, le=31)

    @model_validator(mode="after")
    def validate_allocation(self):
        keys = [(item.market, item.symbol.strip().upper()) for item in self.allocations]
        if len(keys) != len(set(keys)):
            raise ValueError("allocation assets must be unique")
        cash = [item for item in self.allocations if item.market == "cash" or item.asset_type == "cash"]
        if len(cash) != 1 or cash[0].symbol.strip().upper() != "CASH":
            raise ValueError("exactly one CASH allocation is required")
        total = sum(item.weight for item in self.allocations)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"allocation weights must sum to 100%, got {total:.2%}")
        return self


class PortfolioBacktestRequest(PortfolioDefinition):
    years: int = Field(default=5, ge=1, le=10)
    rebalance_months: int = Field(default=3, ge=1, le=12)


class EquityPoint(BaseModel):
    date: str
    value: float
    cumulative_return: float


class AnnualReturn(BaseModel):
    year: int
    return_rate: float


class PortfolioBacktestResult(BaseModel):
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_profit: float
    total_return: float
    cagr: float
    annual_average_return: float
    max_drawdown: float
    annual_volatility: float
    installments: int
    investment_completed_date: str
    rebalances: int
    rebalance_dates: list[str]
    annual_returns: list[AnnualReturn]
    curve: list[EquityPoint]
    warnings: list[str] = Field(default_factory=list)


class TrackerPosition(BaseModel):
    symbol: str
    market: str
    name: str
    target_weight: float
    quantity: float
    price_native: float
    currency: str
    fx_to_usd: float
    value_usd: float
    actual_weight: float
    price_date: str


class TrackingPortfolio(BaseModel):
    tracker_id: str
    status: Literal["building", "active", "stopped"]
    created_at: str
    initial_capital: float
    current_value: float
    cumulative_return: float
    today_return: float
    completed_installments: int
    total_installments: int
    next_installment_date: str | None
    investment_completed_date: str | None
    completed_rebalances: int
    last_rebalance_date: str | None
    next_rebalance_date: str | None
    strategic_cash: float
    deployment_cash: float
    positions: list[TrackerPosition]
    curve: list[EquityPoint]
    last_updated: str
    warnings: list[str] = Field(default_factory=list)
