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


class NewsCenterList(BaseModel):
    items: list[NewsCenterArticle]
    total: int
    sectors: list[str]


class NewsCenterDigest(BaseModel):
    date: str
    article_count: int
    watchlist_count: int
    positive_count: int
    negative_count: int
    summary: str
    major_items: list[NewsCenterArticle]


class NewsCenterRefreshResult(BaseModel):
    fetched: int
    total: int
    latest_date: str | None = None
