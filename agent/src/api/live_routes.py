"""Live-trading surface HTTP routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI


def register_live_routes(app: FastAPI, host: Any) -> None:
    router = APIRouter()
    auth = [Depends(host.require_auth)]

    router.add_api_route(
        "/mandate/commit",
        host.commit_mandate_endpoint,
        methods=["POST"],
        dependencies=auth,
    )
    router.add_api_route(
        "/live/halt",
        host.halt_live_endpoint,
        methods=["POST"],
        dependencies=auth,
    )
    router.add_api_route(
        "/live/resume",
        host.resume_live_endpoint,
        methods=["POST"],
        dependencies=auth,
    )
    router.add_api_route(
        "/live/status",
        host.live_status_endpoint,
        methods=["GET"],
        response_model=host.LiveStatusResponse,
        dependencies=auth,
    )
    router.add_api_route(
        "/live/authorize",
        host.live_authorize_endpoint,
        methods=["POST"],
        dependencies=auth,
    )
    router.add_api_route(
        "/live/runner/start",
        host.start_runner_endpoint,
        methods=["POST"],
        dependencies=auth,
    )
    router.add_api_route(
        "/live/runner/stop",
        host.stop_runner_endpoint,
        methods=["POST"],
        dependencies=auth,
    )
    app.include_router(router)
