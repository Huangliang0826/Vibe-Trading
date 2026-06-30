"""Pydantic contracts for the opportunity center."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCORE_VERSION = "opportunity-v1"
STRATEGY_VERSION = "oos-holdout-v1"

Market = Literal["hk", "us"]
OpportunityLevel = Literal["优先关注", "值得观察", "暂不参与", "数据不足"]
StrategyAction = Literal["entry", "add", "hold", "exit", "risk_exit", "wait", "none"]
MatchLevel = Literal["direct", "industry", "macro"]
ImpactDirection = Literal["positive", "neutral", "negative"]


class OpportunityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DimensionScores(OpportunityContract):
    strategy: float | None = Field(None, ge=0, le=100)
    trend: float | None = Field(None, ge=0, le=100)
    risk: float | None = Field(None, ge=0, le=100)
    news: float | None = Field(None, ge=0, le=100)
    valuation: float | None = Field(None, ge=0, le=100)


class NewsArticle(OpportunityContract):
    article_id: str
    source: str
    title: str
    url: str
    published_at: str
    summary: str = ""


class NewsImpact(OpportunityContract):
    article_id: str
    market: Market
    code: str
    direction: ImpactDirection
    strength: float | None = Field(None, ge=0, le=100)
    confidence: float | None = Field(None, ge=0, le=100)
    horizon: str
    summary: str = ""
    rationale: str = ""
    match_level: MatchLevel = "direct"
    published_at: str | None = None
    title: str = ""
    source: str = ""
    url: str = ""


class StockContext(OpportunityContract):
    market: Market
    code: str
    company_name: str
    aliases: list[str] = Field(default_factory=list)
    brands: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    sector: str = ""
    industry: str = ""


class StrategyContext(OpportunityContract):
    strategy_name: str | None = None
    strategy_label: str | None = None
    action: StrategyAction = "none"
    signal_date: str | None = None
    current_weight: float | None = Field(None, ge=0, le=100)
    oos_total_return: float | None = None
    oos_max_drawdown: float | None = None
    oos_sharpe: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    data_as_of: str | None = None


class MarketContext(OpportunityContract):
    market: Market
    code: str
    latest_price_date: str
    trend_score: float | None = Field(None, ge=0, le=100)
    risk_score: float | None = Field(None, ge=0, le=100)
    trend_inputs: dict[str, Any] = Field(default_factory=dict)
    risk_inputs: dict[str, Any] = Field(default_factory=dict)
    valuation_percentile: float | None = Field(None, ge=0, le=100)


class OpportunityItem(OpportunityContract):
    market: Market
    code: str
    company_name: str
    snapshot_date: str
    score: float | None = Field(None, ge=0, le=100)
    score_change: float | None = None
    level: OpportunityLevel
    latest_action: StrategyAction = "none"
    signal_date: str | None = None
    strategy_name: str | None = None
    strategy_label: str | None = None
    primary_reason: str = ""
    risk_reasons: list[str] = Field(default_factory=list)
    dimensions: DimensionScores = Field(default_factory=DimensionScores)
    data_as_of: str
    stale: bool = False
    degraded: bool = False
    missing_dimensions: list[str] = Field(default_factory=list)
    score_version: str
    strategy_version: str


class OpportunityDetail(OpportunityItem):
    news: list[NewsImpact] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)
    history_available: bool = False


class RefreshJob(OpportunityContract):
    job_id: str
    status: str
    markets: list[Market] = Field(default_factory=list)
    trigger: str
    completed: int = Field(0, ge=0)
    total: int = Field(0, ge=0)
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None
    error: str | None = None


class OpportunityList(OpportunityContract):
    items: list[OpportunityItem] = Field(default_factory=list)
    latest_success_at: str | None = None
    active_job: RefreshJob | None = None
    last_refresh_error: str | None = None
