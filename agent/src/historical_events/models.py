from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


EventDirection = Literal["up", "down"]
AssetType = Literal["stock", "etf"]
EventMarket = Literal["cn", "hk", "us"]
Confidence = Literal["高", "中", "低"]


class DetectedEvent(BaseModel):
    start_date: date
    end_date: date
    direction: EventDirection
    return_pct: float
    trigger_windows: list[int] = Field(default_factory=list)
    volatility_filter_available: bool = True


class EvidenceItem(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    published_at: date | None = None
    evidence_type: str = "财经新闻"
    related_symbols: list[str] = Field(default_factory=list)


class HistoricalEvent(DetectedEvent):
    event_id: str
    market: EventMarket
    symbol: str
    company_name: str
    benchmark_symbol: str = ""
    benchmark_return_pct: float | None = None
    relative_return_pct: float | None = None
    market_context: str = "原因未确认"
    driver_type: str
    primary_driver: str
    narrative: str
    confidence: Confidence
    evidence: list[EvidenceItem] = Field(default_factory=list)
    alternative_factors: list[str] = Field(default_factory=list)
    causality_note: str = "新闻与价格波动的时间相关性不等于已证明的因果关系。"
    detector_version: str = "major-move-v1"
    analysis_version: str = "historical-event-analysis-v1"
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HistoricalEventRun(BaseModel):
    run_id: str
    market: EventMarket
    symbol: str
    company_name: str
    period: Literal["1Y", "3Y", "5Y", "ALL"]
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    progress: int = 0
    stage: str = "等待开始"
    cached: bool = False
    event_count: int = 0
    error: str | None = None
    analysis_version: str = "historical-event-analysis-v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
