"""Read-only agent tool: surface the latest opportunity scan.

Auto-discovered via BaseTool.__subclasses__(). Reads the persisted ScanResult;
it never recomputes or fabricates — if no scan exists it says so.
"""
from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.scanner.store import load_latest


class OpportunityScanTool(BaseTool):
    """Return the most recent US-equity opportunity scan leaderboard."""

    name = "opportunity_scan"
    description = (
        "Return the most recent US-equity opportunity scan: a ranked list of "
        "candidate tickers with composite scores and human-readable attribution "
        "(why each made the list). Read-only research output — not investment "
        "advice, places no orders. Returns an error if no scan has been run yet."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs: Any) -> str:
        result = load_latest()
        if result is None:
            return json.dumps(
                {"status": "error",
                 "error": "no scan available; run 'vibe-trading scan run --asof <date>'"},
                ensure_ascii=False,
            )
        return json.dumps({"status": "ok", "scan": result.to_dict()}, ensure_ascii=False)
