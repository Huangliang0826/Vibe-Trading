"""FastAPI routes for personal asset-allocation plans."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from src.asset_management import (
    PortfolioBacktestRequest,
    PortfolioBacktestResult,
    PortfolioBacktestService,
    PortfolioDefinition,
    TrackingPortfolio,
    TrackingStore,
)


def register_asset_management_routes(
    app: FastAPI,
    *,
    require_auth: Callable[..., Any],
) -> None:
    backtester = PortfolioBacktestService()
    tracking = TrackingStore()

    async def backtest_portfolio(payload: PortfolioBacktestRequest) -> PortfolioBacktestResult:
        try:
            return await asyncio.to_thread(backtester.run, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def start_tracking(payload: PortfolioDefinition) -> TrackingPortfolio:
        try:
            return await asyncio.to_thread(tracking.create, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def latest_tracking() -> TrackingPortfolio | None:
        try:
            return await asyncio.to_thread(tracking.latest)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    app.add_api_route(
        "/asset-management/backtest",
        backtest_portfolio,
        methods=["POST"],
        response_model=PortfolioBacktestResult,
        dependencies=[Depends(require_auth)],
    )
    app.add_api_route(
        "/asset-management/tracking",
        start_tracking,
        methods=["POST"],
        response_model=TrackingPortfolio,
        dependencies=[Depends(require_auth)],
    )
    app.add_api_route(
        "/asset-management/tracking/latest",
        latest_tracking,
        methods=["GET"],
        response_model=TrackingPortfolio | None,
        dependencies=[Depends(require_auth)],
    )
