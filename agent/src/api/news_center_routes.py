from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Response

from src.news_center.models import NewsCenterDigest, NewsCenterList, NewsCenterRefreshResult
from src.news_center.service import NewsCenterService

AuthDep = Callable[..., Awaitable[Any] | Any]
logger = logging.getLogger(__name__)


def register_news_center_routes(
    app: FastAPI,
    *,
    require_auth: AuthDep,
    service: NewsCenterService | None = None,
) -> None:
    service = service or NewsCenterService()
    ai_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}

    def with_generation_state(digest: NewsCenterDigest, date_key: str, language: str) -> NewsCenterDigest:
        task = ai_tasks.get((date_key, language))
        digest.ai_enriching = bool(task and not task.done())
        return digest

    async def run_enrichment(date_key: str, language: str, force: bool) -> None:
        try:
            await asyncio.to_thread(service.enrich_ai_digest, date_key, language, force)
        except Exception:  # noqa: BLE001 — local digest remains available on enrichment failure
            logger.exception("news AI web enrichment failed for %s/%s", date_key, language)
        finally:
            ai_tasks.pop((date_key, language), None)

    def schedule_enrichment(date_key: str, language: str, force: bool = False) -> None:
        key = (date_key, language)
        task = ai_tasks.get(key)
        if task is None or task.done():
            ai_tasks[key] = asyncio.create_task(run_enrichment(date_key, language, force))
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
        language: Literal["zh", "en"] = "zh",
        limit: int = Query(200, ge=1, le=500),
    ) -> NewsCenterList:
        response.headers["Cache-Control"] = "no-store"
        return service.list_articles(
            date_key=date_key, sector=sector, direction=direction, query=query,
            symbol=symbol, watchlist_only=watchlist_only, limit=limit,
            language=language,
        )

    @router.get("/dates", response_model=list[str])
    async def dates(response: Response) -> list[str]:
        response.headers["Cache-Control"] = "no-store"
        return service.get_dates()

    @router.get("/digest", response_model=NewsCenterDigest)
    async def digest(
        response: Response,
        date_key: str = Query(..., alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
        language: Literal["zh", "en"] = "zh",
    ) -> NewsCenterDigest:
        response.headers["Cache-Control"] = "no-store"
        return with_generation_state(
            service.get_digest(date_key, language=language), date_key, language,
        )

    @router.post("/ai-digest", response_model=NewsCenterDigest)
    async def ai_digest(
        response: Response,
        date_key: str = Query(..., alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
        language: Literal["zh", "en"] = "zh",
        force: bool = False,
    ) -> NewsCenterDigest:
        """Return immediately and generate the direct web briefing in background."""
        response.headers["Cache-Control"] = "no-store"
        digest_result = service.get_digest(date_key, language=language)
        if language == "zh" and (force or digest_result.ai_source != "web"):
            schedule_enrichment(date_key, language, force)
        return with_generation_state(digest_result, date_key, language)

    @router.post("/refresh", response_model=NewsCenterRefreshResult)
    async def refresh(response: Response) -> NewsCenterRefreshResult:
        response.headers["Cache-Control"] = "no-store"
        return await asyncio.to_thread(service.refresh)

    app.include_router(router)
