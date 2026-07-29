from __future__ import annotations

from enum import IntEnum
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, Query, status

from src.analytics.models import EventBatch
from src.analytics.service import AnalyticsService

AuthDep = Callable[..., Awaitable[Any] | Any]

class AnalyticsDays(IntEnum):
    week = 7
    month = 30
    quarter = 90


def register_analytics_routes(
    app: FastAPI,
    *,
    require_auth: AuthDep,
    service: AnalyticsService,
) -> None:
    router = APIRouter(prefix="/api/analytics", dependencies=[Depends(require_auth)])

    @router.post("/events", status_code=status.HTTP_202_ACCEPTED)
    async def collect_events(batch: EventBatch) -> dict[str, int]:
        rejected_before = service.collector.rejected_count
        dropped_before = service.collector.dropped_count
        accepted = sum(service.collector.submit(event) for event in batch.events)
        return {
            "accepted": accepted,
            "rejected": service.collector.rejected_count - rejected_before,
            "dropped": service.collector.dropped_count - dropped_before,
        }

    @router.get("/trends")
    async def trends(
        metric: str = Query(min_length=1, max_length=100),
        days: AnalyticsDays = 30,
    ) -> dict[str, Any]:
        return service.trends(metric, int(days))

    @router.get("/usage")
    async def usage(days: AnalyticsDays = 30) -> dict[str, Any]:
        return service.usage(int(days))

    @router.get("/system-health")
    async def system_health(days: AnalyticsDays = 30) -> dict[str, Any]:
        return service.system_health(int(days))

    @router.get("/research-quality")
    async def research_quality(
        days: AnalyticsDays = 30,
        subject: str = Query("scanner", min_length=1, max_length=40),
        market: str | None = Query(None, max_length=20),
        horizon: str | None = Query(None, max_length=20),
        regime: str | None = Query("all", max_length=40),
    ) -> dict[str, Any]:
        return service.research_quality(
            days=int(days),
            subject=subject,
            market=market,
            horizon=horizon,
            regime=regime,
        )

    @router.get("/edge-scorecard")
    async def edge_scorecard(
        days: AnalyticsDays = 90,
        cost_bps: float = Query(15.0, ge=0, le=200),
    ) -> dict[str, Any]:
        return service.edge_scorecard(days=int(days), cost_bps=cost_bps)

    @router.get("/development")
    async def development(
        days: AnalyticsDays = 30,
        release: str | None = Query(None, max_length=40),
        window_days: int = Query(7),
    ) -> dict[str, Any]:
        if window_days not in {7, 30}:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="window_days must be 7 or 30")
        return service.development(days=int(days), release=release, window_days=window_days)

    app.include_router(router)
