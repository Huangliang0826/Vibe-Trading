"""FastAPI routes for personal asset-allocation plans."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from src.asset_management import AssetManagementPlan, AssetManagementRequest, AssetManagementService


def register_asset_management_routes(
    app: FastAPI,
    *,
    require_auth: Callable[..., Any],
    service: AssetManagementService | None = None,
) -> None:
    planner = service or AssetManagementService()

    async def get_latest_asset_plan() -> AssetManagementPlan | None:
        return planner.get_latest()

    async def calculate_asset_plan(payload: AssetManagementRequest) -> AssetManagementPlan:
        try:
            return await asyncio.to_thread(planner.calculate, payload)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    app.add_api_route(
        "/asset-management/latest",
        get_latest_asset_plan,
        methods=["GET"],
        response_model=AssetManagementPlan | None,
        dependencies=[Depends(require_auth)],
    )
    app.add_api_route(
        "/asset-management/calculate",
        calculate_asset_plan,
        methods=["POST"],
        response_model=AssetManagementPlan,
        dependencies=[Depends(require_auth)],
    )
