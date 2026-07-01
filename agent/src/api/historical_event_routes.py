from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field

from src.historical_events.models import HistoricalEvent, HistoricalEventRun
from src.historical_events.service import HistoricalEventService

AuthDep = Callable[..., Awaitable[Any] | Any]
Market = Literal["hk", "us"]
Period = Literal["1Y", "3Y", "5Y", "ALL"]


class HistoricalEventRunRequest(BaseModel):
    market: Market
    code: str = Field(min_length=1, max_length=30)
    company_name: str = Field(default="", max_length=100)
    period: Period
    force: bool = False


def register_historical_event_routes(
    app: FastAPI, *, require_auth: AuthDep,
    service: HistoricalEventService | None = None,
) -> None:
    service = service or HistoricalEventService()
    router = APIRouter(prefix="/historical-events", dependencies=[Depends(require_auth)])
    tasks: set[asyncio.Task[Any]] = set()

    @router.post("/runs", response_model=HistoricalEventRun, status_code=status.HTTP_202_ACCEPTED)
    async def create_run(payload: HistoricalEventRunRequest, response: Response) -> HistoricalEventRun:
        response.headers["Cache-Control"] = "no-store"
        try:
            run = service.start_run(
                payload.market, payload.code, payload.company_name, payload.period, payload.force,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if run.status == "pending":
            task = asyncio.create_task(asyncio.to_thread(service.run, run.run_id))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        return run

    @router.get("/runs/{run_id}", response_model=HistoricalEventRun)
    async def get_run(run_id: str, response: Response) -> HistoricalEventRun:
        response.headers["Cache-Control"] = "no-store"
        run = service.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="historical event run not found")
        return run

    @router.get("/{market}/{code}", response_model=list[HistoricalEvent])
    async def list_events(market: Market, code: str, period: Period, response: Response) -> list[HistoricalEvent]:
        response.headers["Cache-Control"] = "no-store"
        return service.list_events(market, code, period)

    app.include_router(router)
