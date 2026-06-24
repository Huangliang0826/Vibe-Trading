"""Forecast HTTP routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI


def register_forecast_routes(app: FastAPI, host: Any) -> None:
    router = APIRouter()

    router.add_api_route("/forecast/{market}/{code}", host.get_forecast, methods=["GET"])
    router.add_api_route(
        "/forecast/{market}/{code}/calibration",
        host.get_forecast_calibration,
        methods=["GET"],
    )
    router.add_api_route(
        "/forecast/{market}/{code}/strategy",
        host.get_forecast_strategy,
        methods=["GET"],
    )
    router.add_api_route(
        "/forecast/robustness",
        host.get_strategy_robustness,
        methods=["GET"],
    )
    app.include_router(router)
