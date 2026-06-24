"""Settings HTTP routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI


def register_settings_routes(app: FastAPI, host: Any) -> None:
    router = APIRouter()
    local_or_auth = [Depends(host.require_local_or_auth)]

    router.add_api_route(
        "/settings/llm",
        host.get_llm_settings,
        methods=["GET"],
        response_model=host.LLMSettingsResponse,
        dependencies=local_or_auth,
    )
    router.add_api_route(
        "/settings/llm",
        host.update_llm_settings,
        methods=["PUT"],
        response_model=host.LLMSettingsResponse,
        dependencies=local_or_auth,
    )
    router.add_api_route(
        "/settings/data-sources",
        host.get_data_source_settings,
        methods=["GET"],
        response_model=host.DataSourceSettingsResponse,
        dependencies=local_or_auth,
    )
    router.add_api_route(
        "/settings/data-sources",
        host.update_data_source_settings,
        methods=["PUT"],
        response_model=host.DataSourceSettingsResponse,
        dependencies=local_or_auth,
    )
    app.include_router(router)
