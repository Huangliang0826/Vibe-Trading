"""Market-data and research-data HTTP routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI


def register_market_data_routes(app: FastAPI, host: Any) -> None:
    router = APIRouter()

    router.add_api_route("/correlation", host.get_correlation_matrix, methods=["GET"])
    router.add_api_route("/market-indices", host.get_market_indices, methods=["GET"])
    router.add_api_route("/research/industry-reports", host.get_industry_reports, methods=["GET"])
    router.add_api_route("/research/hstech-reports", host.get_hstech_reports, methods=["GET"])
    router.add_api_route("/watchlist/quote", host.get_watchlist_quote, methods=["GET"])
    router.add_api_route("/watchlist/history", host.get_watchlist_history, methods=["GET"])
    router.add_api_route("/hstech/news", host.get_hstech_news, methods=["GET"])
    router.add_api_route("/hstech/unified-strategy", host.get_hstech_unified_strategy, methods=["GET"])
    router.add_api_route("/watchlist/valuation", host.get_watchlist_valuation, methods=["GET"])
    app.include_router(router)
