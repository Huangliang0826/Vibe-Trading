"""Run-result HTTP routes.

The handlers currently live in ``api_server.py``; this module owns the route
registration so the API surface can be split incrementally without changing
behavior.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI


def register_runs_routes(app: FastAPI, host: Any) -> None:
    router = APIRouter()
    auth = [Depends(host.require_auth)]

    router.add_api_route(
        "/runs/{run_id}/code",
        host.get_run_code,
        methods=["GET"],
        dependencies=auth,
    )
    router.add_api_route(
        "/runs/{run_id}/pine",
        host.get_run_pine,
        methods=["GET"],
        dependencies=auth,
    )
    router.add_api_route(
        "/runs/{run_id}",
        host.get_run_result,
        methods=["GET"],
        response_model=host.RunResponse,
        dependencies=auth,
    )
    router.add_api_route(
        "/runs",
        host.list_runs,
        methods=["GET"],
        response_model=list[host.RunInfo],
        dependencies=auth,
    )
    app.include_router(router)
