"""Models for local research analysis runs."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


Rating = Literal["buy", "hold", "sell"]


class ResearchAnalysisStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ResearchAnalysisCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    market: Literal["us", "hk", "auto"] = "auto"
    analysis_date: str | None = Field(default=None, description="YYYY-MM-DD; defaults to today")


class ResearchAnalysisReport(BaseModel):
    rating: Rating
    confidence: int = Field(ge=0, le=100)
    horizon: str
    summary: str
    bull_case: str
    bear_case: str
    technical_view: str
    fundamental_view: str
    sentiment_news_view: str
    risk_factors: list[str]
    suggested_action: str
    disclaimer: str
    structured: bool = True


class ResearchAnalysisRun(BaseModel):
    run_id: str
    symbol: str
    market: str
    company_name: str | None = None
    analysis_date: str
    created_at: str
    updated_at: str
    status: ResearchAnalysisStatus
    rating: Rating | None = None
    confidence: int | None = None
    summary: str = ""
    report: ResearchAnalysisReport | None = None
    report_markdown: str = ""
    raw_decision: Any | None = None
    error: str | None = None
    analysis_config: dict[str, Any] = Field(default_factory=dict)


class ResearchAnalysisList(BaseModel):
    items: list[ResearchAnalysisRun]
