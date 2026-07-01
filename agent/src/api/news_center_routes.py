from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Response

from src.news_center.models import NewsCenterDigest, NewsCenterList, NewsCenterRefreshResult
from src.news_center.service import NewsCenterService

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_news_center_routes(
    app: FastAPI,
    *,
    require_auth: AuthDep,
    service: NewsCenterService | None = None,
) -> None:
    service = service or NewsCenterService()
    router = APIRouter(prefix="/news-center", dependencies=[Depends(require_auth)])

    @router.get("/articles", response_model=NewsCenterList)
    async def articles(
        response: Response,
        date_key: str | None = Query(None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
        sector: str | None = None,
        direction: Literal["positive", "neutral", "negative"] | None = None,
        query: str | None = Query(None, max_length=100),
        symbol: str | None = Query(None, max_length=30),
        watchlist_only: bool = False,
        limit: int = Query(200, ge=1, le=500),
    ) -> NewsCenterList:
        response.headers["Cache-Control"] = "no-store"
        return service.list_articles(
            date_key=date_key, sector=sector, direction=direction, query=query,
            symbol=symbol, watchlist_only=watchlist_only, limit=limit,
        )

    @router.get("/dates", response_model=list[str])
    async def dates(response: Response) -> list[str]:
        response.headers["Cache-Control"] = "no-store"
        return service.get_dates()

    @router.get("/digest", response_model=NewsCenterDigest)
    async def digest(
        response: Response,
        date_key: str = Query(..., alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> NewsCenterDigest:
        response.headers["Cache-Control"] = "no-store"
        return service.get_digest(date_key)

    @router.post("/refresh", response_model=NewsCenterRefreshResult)
    async def refresh(response: Response) -> NewsCenterRefreshResult:
        response.headers["Cache-Control"] = "no-store"
        return await asyncio.to_thread(service.refresh)

    app.include_router(router)
