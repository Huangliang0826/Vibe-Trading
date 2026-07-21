"""Contracts for the personal asset-allocation planner."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AssetCandidate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    market: Literal["us", "hk", "cn"]
    name: str = Field(default="", max_length=100)
    asset_type: Literal["stock", "fund", "bond"] = "stock"


class AssetManagementRequest(BaseModel):
    candidates: list[AssetCandidate] = Field(..., min_length=1, max_length=20)
    target_return: float = Field(..., ge=0.03, le=0.12)
    max_drawdown: float = Field(..., ge=0.10, le=0.35)
    lookback_years: int = Field(default=5, ge=3, le=10)

    @model_validator(mode="after")
    def unique_candidates(self):
        keys = [(item.market, item.symbol.strip().upper()) for item in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("candidate symbols must be unique within each market")
        return self


class AllocationItem(BaseModel):
    symbol: str
    market: Literal["us", "hk", "cn", "cash"]
    name: str
    asset_type: Literal["stock", "fund", "bond", "cash"]
    weight: float
    range_min: float
    range_max: float
    risk_contribution: float
    expected_return: float
    reason: str


class PortfolioMetrics(BaseModel):
    expected_return: float
    annual_volatility: float
    historical_max_drawdown: float
    stress_drawdown: float
    target_return: float
    max_drawdown_limit: float


class AssetManagementPlan(BaseModel):
    plan_id: str
    status: Literal["feasible", "closest"]
    created_at: str
    data_through: str
    provider: str
    model: str
    optimizer_version: str = "asset-allocation.deepseek.v2"
    request: AssetManagementRequest
    allocations: list[AllocationItem]
    metrics: PortfolioMetrics
    summary: str
    warnings: list[str] = Field(default_factory=list)
