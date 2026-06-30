"""FastAPI routes for the watchlist opportunity center."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, Field

from src.opportunity_center.models import (
    OpportunityDetail,
    OpportunityCalibrationSummary,
    OpportunityItem,
    OpportunityLevel,
    OpportunityList,
    RefreshJob,
    StrategyAction,
)
from src.opportunity_center.scheduler import OpportunityScheduler
from src.opportunity_center.service import OpportunityService

AuthDep = Callable[..., Awaitable[Any] | Any]
MarketParam = Literal["hk", "us"]


class RefreshRequest(BaseModel):
    markets: list[MarketParam] = Field(default_factory=lambda: ["hk", "us"], min_length=1)
    force: bool = False


@dataclass
class OpportunityRuntime:
    service: OpportunityService
    scheduler: OpportunityScheduler
    tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)

    async def stop(self) -> None:
        await self.scheduler.stop()
        pending = [task for task in self.tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()


def register_opportunity_routes(
    app: FastAPI,
    *,
    require_auth: AuthDep,
    service: OpportunityService | None = None,
    scheduler: OpportunityScheduler | None = None,
    start_scheduler: bool = False,
) -> OpportunityRuntime:
    service = service or OpportunityService()
    runtime = OpportunityRuntime(service=service, scheduler=scheduler or OpportunityScheduler(service))
    router = APIRouter(prefix="/opportunities", dependencies=[Depends(require_auth)])

    @router.get("", response_model=OpportunityList)
    async def list_opportunities(
        response: Response,
        market: MarketParam | None = None,
        signal: StrategyAction | None = None,
        level: OpportunityLevel | None = None,
    ) -> OpportunityList:
        _no_store(response)
        try:
            return service.get_list(market=market, signal=signal, level=level)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"opportunity list failed: {exc}") from exc

    # Static refresh paths must be registered before the dynamic market/code paths.
    @router.post("/refresh", response_model=RefreshJob, status_code=status.HTTP_202_ACCEPTED)
    async def create_refresh(payload: RefreshRequest, response: Response) -> RefreshJob:
        _no_store(response)
        try:
            job = service.start_refresh(payload.markets, "manual", payload.force)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"opportunity refresh failed: {exc}") from exc
        if job.status == "queued" and job.job_id not in runtime.tasks:
            task = asyncio.create_task(service.run_job(job.job_id))
            runtime.tasks[job.job_id] = task
            task.add_done_callback(lambda done, job_id=job.job_id: _finish_task(runtime, job_id, done))
        return job

    @router.get("/refresh/{job_id}", response_model=RefreshJob)
    async def get_refresh_job(response: Response, job_id: str = Path(min_length=1, max_length=100)) -> RefreshJob:
        _no_store(response)
        job = service.store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="opportunity refresh job not found")
        return job

    @router.get("/calibration", response_model=OpportunityCalibrationSummary)
    async def get_calibration(
        response: Response,
        scope: Literal["top3", "all"] = "top3",
    ) -> OpportunityCalibrationSummary:
        _no_store(response)
        try:
            return service.get_calibration(scope)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"opportunity calibration failed: {exc}") from exc

    @router.get("/{market}/{code}/history", response_model=list[OpportunityItem])
    async def opportunity_history(
        response: Response,
        market: MarketParam,
        code: str,
        limit: int = Query(30, ge=1, le=500),
    ) -> list[OpportunityItem]:
        _no_store(response)
        normalized = _validate_code(market, code)
        return service.get_history(market, normalized, limit)

    @router.get("/{market}/{code}", response_model=OpportunityDetail)
    async def opportunity_detail(
        response: Response,
        market: MarketParam,
        code: str,
        snapshot_date: str | None = Query(None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> OpportunityDetail:
        _no_store(response)
        normalized = _validate_code(market, code)
        detail = service.get_detail(market, normalized, snapshot_date)
        if detail is None:
            raise HTTPException(status_code=404, detail="opportunity snapshot not found")
        return detail

    app.include_router(router)
    if start_scheduler:
        @app.on_event("startup")
        async def _start_opportunity_scheduler() -> None:
            runtime.scheduler.start()

        @app.on_event("shutdown")
        async def _stop_opportunity_scheduler() -> None:
            await runtime.stop()
    return runtime


def _validate_code(market: str, code: str) -> str:
    value = code.strip().upper()
    pattern = r"(?:0?\d{4,5})(?:\.HK)?" if market == "hk" else r"[A-Z][A-Z0-9.-]{0,14}"
    if not re.fullmatch(pattern, value):
        raise HTTPException(status_code=400, detail=f"invalid {market} stock code")
    if market == "hk":
        digits = "".join(character for character in value.split(".")[0] if character.isdigit())
        return f"{int(digits):04d}"
    return value


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _finish_task(runtime: OpportunityRuntime, job_id: str, task: asyncio.Task[None]) -> None:
    runtime.tasks.pop(job_id, None)
    if not task.cancelled():
        task.exception()
