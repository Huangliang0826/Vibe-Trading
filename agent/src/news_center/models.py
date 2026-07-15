from __future__ import annotations

from pydantic import BaseModel, Field


class NewsCenterMatch(BaseModel):
    market: str
    code: str
    match_level: str
    confidence: float = 0
    direction: str | None = None
    strength: float | None = None


class NewsCenterArticle(BaseModel):
    article_id: str
    source: str
    title: str
    url: str
    published_at: str
    summary: str = ""
    sector: str = ""
    matches: list[NewsCenterMatch] = Field(default_factory=list)
    importance: float = 0
    major: bool = False
    language: str = "zh"


class NewsCenterList(BaseModel):
    items: list[NewsCenterArticle]
    total: int
    sectors: list[str]


class NewsAiMajorItem(BaseModel):
    title: str
    summary: str = ""
    impact: str = "neutral"


class NewsCenterDigest(BaseModel):
    date: str
    article_count: int
    watchlist_count: int
    positive_count: int
    negative_count: int
    summary: str
    major_items: list[NewsCenterArticle]
    ai_summary: str | None = None
    ai_major: list[NewsAiMajorItem] = Field(default_factory=list)
    ai_generated_at: str | None = None
    ai_model: str | None = None
    ai_source: str | None = None
    ai_enriching: bool = False


class NewsCenterRefreshResult(BaseModel):
    fetched: int
    total: int
    latest_date: str | None = None
