from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalyticsEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    kind: Literal["product", "system", "quality", "development"]
    occurred_at: datetime
    workspace_id: str = "local"
    user_id: str = "local"
    session_id: str | None = None
    feature: str
    action: str
    outcome: Literal["success", "failure", "cancelled", "unknown"] = "unknown"
    duration_ms: int | None = Field(default=None, ge=0)
    app_version: str | None = None
    commit_sha: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventBatch(BaseModel):
    events: list[AnalyticsEvent] = Field(min_length=1, max_length=100)


class MetricPoint(BaseModel):
    bucket: str
    granularity: Literal["hour", "day", "release"]
    domain: Literal["usage", "system", "data", "research", "development", "health"]
    metric: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    value: float | None
    numerator: float | None = None
    denominator: float | None = None
    sample_count: int = Field(ge=0)
    interval_low: float | None = None
    interval_high: float | None = None
    calculation_version: str
