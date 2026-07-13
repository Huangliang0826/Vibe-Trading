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

    app.include_router(router)
