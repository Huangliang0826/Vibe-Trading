"""Scanner REST routes, mounted by api_server.py via register_scan_routes().

Kept out of the api_server.py monolith on purpose (mirrors alpha_routes.py).
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException

from src.scanner.store import load_latest
from src.scanner.tracking import (
    backfill_returns, calibration_check, load_all_tracking, load_tracking,
)

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_scan_routes(app: FastAPI, require_auth: AuthDep | None = None) -> None:
    """Mount scanner routes onto ``app``.

    Args:
        app: Host FastAPI app.
        require_auth: Header-auth dependency; resolved from the api_server host
            module when not passed (back-compat with register_alpha_routes).
    """
    if require_auth is None:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if host is None:  # pragma: no cover
            raise RuntimeError(
                "register_scan_routes: api_server not in sys.modules; pass require_auth"
            )
        require_auth = host.require_auth

    @app.get("/scan/latest", dependencies=[Depends(require_auth)])
    async def scan_latest() -> dict[str, Any]:
        """Return the most recent scan, or 404 when none exist."""
        result = load_latest()
        if result is None:
            raise HTTPException(status_code=404, detail="no scans available")
        return result.to_dict()

    @app.get("/scan/tracking/{asof}", dependencies=[Depends(require_auth)])
    async def scan_tracking(asof: str) -> dict[str, Any]:
        """Return tracking records for a specific scan date."""
        records = load_tracking(asof)
        if not records:
            raise HTTPException(status_code=404, detail=f"no tracking for {asof}")
        return {"asof": asof, "records": [r.to_dict() for r in records]}

    @app.get("/scan/tracking", dependencies=[Depends(require_auth)])
    async def scan_tracking_all() -> dict[str, Any]:
        """Return all tracking records across all scan dates."""
        records = load_all_tracking()
        return {"records": [r.to_dict() for r in records], "total": len(records)}

    @app.get("/scan/calibration", dependencies=[Depends(require_auth)])
    async def scan_calibration() -> dict[str, Any]:
        """Run calibration check and return alerts."""
        records = load_all_tracking()
        alerts = calibration_check(records)
        return {
            "total_tracked": len(records),
            "filled": len([r for r in records if r.fwd_5d is not None]),
            "alerts": [
                {
                    "metric": a.metric,
                    "predicted_mean": a.predicted_mean,
                    "actual_mean": a.actual_mean,
                    "divergence_pp": a.divergence_pp,
                    "n_samples": a.n_samples,
                    "message": a.message,
                }
                for a in alerts
            ],
            "ok": len(alerts) == 0,
        }
