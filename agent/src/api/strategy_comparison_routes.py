"""FastAPI routes for asynchronous fixed-strategy comparisons."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Response, status

from src.paper_trading.comparison_models import StrategyComparisonCreate, StrategyComparisonRun
from src.paper_trading.comparison_service import run_strategy_comparison
from src.paper_trading.comparison_storage import StrategyComparisonStore

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_strategy_comparison_routes(
    app: FastAPI,
    *,
    require_auth: AuthDep,
    store: StrategyComparisonStore | None = None,
    executor: Callable[[str, StrategyComparisonStore], Any] = run_strategy_comparison,
) -> None:
    comparison_store = store or StrategyComparisonStore()
    tasks: set[asyncio.Task[Any]] = set()

    @app.post(
        "/paper-trading/strategy-comparisons",
        response_model=StrategyComparisonRun,
        dependencies=[Depends(require_auth)],
    )
    async def create_strategy_comparison(
        payload: StrategyComparisonCreate, response: Response,
    ) -> StrategyComparisonRun:
        response.headers["Cache-Control"] = "no-store"
        run = comparison_store.create_or_reuse(payload)
        if run.cache_hit:
            response.status_code = status.HTTP_200_OK
            return run
        response.status_code = status.HTTP_202_ACCEPTED
        task = asyncio.create_task(asyncio.to_thread(executor, run.run_id, comparison_store))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return run

    @app.get(
        "/paper-trading/strategy-comparisons/{run_id}",
        response_model=StrategyComparisonRun,
        dependencies=[Depends(require_auth)],
    )
    async def get_strategy_comparison(run_id: str, response: Response) -> StrategyComparisonRun:
        response.headers["Cache-Control"] = "no-store"
        try:
            run = comparison_store.get(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if run is None:
            raise HTTPException(status_code=404, detail="strategy comparison not found")
        return run
