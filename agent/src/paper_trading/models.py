"""Pydantic models for paper trading backtests."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class PaperTradingStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class PaperHolding(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    market: Literal["us", "hk", "cn"] = "us"
    allocation_pct: float = Field(..., gt=0, le=100)


class StrategyConfig(BaseModel):
    name: Literal[
        "buy_and_hold",
        "dca",
        "grid",
        "momentum_breakout",
        "moving_average_cross",
        "rsi_reversion",
        "volatility_target",
        "drawdown_rebalance",
        "smart_dca",
        "dca_then_hold",
        "trend_volatility_filter",
        "donchian_breakout",
        "bollinger_reversion",
        "trailing_stop",
        "monthly_rebalance",
        "macd_divergence",
        "dual_momentum",
        "vol_trend_rotation",
        "atr_trend_stop",
        "mean_reversion_scaleout",
        "enhanced_dca_trend",
        "breakout_pullback",
        "quality_momentum",
        "low_volatility_rotation",
        "volatility_squeeze_breakout",
        "risk_parity",
        "price_volume_efficiency",
    ] = "buy_and_hold"
    params: dict[str, Any] = Field(default_factory=dict)


class PaperTradingCreate(BaseModel):
    title: str = ""
    holdings: list[PaperHolding] = Field(..., min_length=1)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_usd: float = Field(default=100_000.0, gt=0)
    initial_hkd: float = Field(default=1_000_000.0, ge=0)


class PaperTradingRun(BaseModel):
    run_id: str
    title: str = ""
    holdings: list[PaperHolding] = Field(default_factory=list)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    start_date: str = ""
    end_date: str = ""
    initial_usd: float = 100_000.0
    initial_hkd: float = 1_000_000.0
    initial_total_usd: float = 0.0
    status: PaperTradingStatus = PaperTradingStatus.queued
    created_at: str = ""
    updated_at: str = ""
    metrics: dict[str, Any] | None = None
    equity_curve: list[dict[str, Any]] | None = None
    trades: list[dict[str, Any]] | None = None
    error: str | None = None


class PaperTradingList(BaseModel):
    items: list[PaperTradingRun]


class RobustStrategySpec(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class RobustOptimizeCreate(BaseModel):
    holdings: list[PaperHolding] = Field(..., min_length=1)
    strategies: list[RobustStrategySpec] = Field(..., min_length=1)
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_usd: float = Field(default=100_000.0, gt=0)
    initial_hkd: float = Field(default=1_000_000.0, ge=0)
    window_years: int = Field(default=3, ge=2, le=10)
    step_years: int = Field(default=2, ge=1, le=5)
