"""Scanner REST routes, mounted by api_server.py via register_scan_routes().

Kept out of the api_server.py monolith on purpose (mirrors alpha_routes.py).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException

from src.scanner.store import list_scan_dates, load_by_date, load_latest, save_scan
from src.scanner.tracking import (
    backfill_returns, calibration_check, compute_accuracy, is_backfill_pending,
    load_all_tracking, load_tracking,
)
from src.scanner.universe_metadata import attach_company_names

AuthDep = Callable[..., Awaitable[Any] | Any]

_SCAN_RESULT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SCAN_RESULT_TTL = 24 * 3600
_SCAN_UNIVERSES = frozenset({"sp500", "hstech"})


def _validate_scan_universe(universe: str) -> str:
    if universe not in _SCAN_UNIVERSES:
        raise HTTPException(
            status_code=400,
            detail=f"universe must be one of {sorted(_SCAN_UNIVERSES)}",
        )
    return universe


def _cache_get(key: str) -> dict[str, Any] | None:
    cached = _SCAN_RESULT_CACHE.get(key)
    if not cached:
        return None
    ts, payload = cached
    if time.time() - ts > _SCAN_RESULT_TTL:
        _SCAN_RESULT_CACHE.pop(key, None)
        return None
    return {**payload, "cached": True}


def _cache_set(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    _SCAN_RESULT_CACHE[key] = (time.time(), payload)
    return {**payload, "cached": False}


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

    @app.post("/scan/run", dependencies=[Depends(require_auth)])
    async def scan_run(universe: str = "sp500", top: int = 20) -> dict[str, Any]:
        """Trigger a new scan for today and return the result."""
        from src.scanner.cli_handlers import _build_scan

        universe = _validate_scan_universe(universe)
        asof = dt.date.today().isoformat()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _build_scan, universe, asof, top)
        save_scan(result)
        return attach_company_names(result).to_dict()

    @app.get("/scan/dates", dependencies=[Depends(require_auth)])
    async def scan_dates(universe: str = "sp500") -> dict[str, Any]:
        """Return available scan dates, most recent first."""
        dates = list_scan_dates(universe=_validate_scan_universe(universe))
        return {"dates": dates}

    @app.get("/scan/history/{asof}", dependencies=[Depends(require_auth)])
    async def scan_by_date(asof: str, universe: str = "sp500") -> dict[str, Any]:
        """Return a scan for a specific date."""
        universe = _validate_scan_universe(universe)
        result = load_by_date(asof, universe=universe)
        if result is None:
            raise HTTPException(status_code=404, detail=f"no scan for {asof}")
        return attach_company_names(result).to_dict()

    @app.get("/scan/latest", dependencies=[Depends(require_auth)])
    async def scan_latest(universe: str = "sp500") -> dict[str, Any]:
        """Return the most recent scan, or 404 when none exist."""
        universe = _validate_scan_universe(universe)
        result = load_latest(universe=universe)
        if result is None:
            raise HTTPException(status_code=404, detail="no scans available")
        return attach_company_names(result).to_dict()

    @app.get("/scan/tracking/{asof}", dependencies=[Depends(require_auth)])
    async def scan_tracking(asof: str, universe: str = "sp500") -> dict[str, Any]:
        """Return tracking records for a specific scan date.

        Backfills forward returns when no records exist yet, and re-backfills
        when stored records are missing returns whose horizon has elapsed.
        """
        universe = _validate_scan_universe(universe)
        records = load_tracking(asof, universe=universe)
        if not records or is_backfill_pending(records, asof):
            result = load_by_date(asof, universe=universe)
            if result is None:
                if not records:
                    raise HTTPException(
                        status_code=404, detail=f"no scan for {asof}"
                    )
            else:
                loop = asyncio.get_running_loop()
                records = await loop.run_in_executor(
                    None,
                    lambda: backfill_returns(
                        asof,
                        [candidate.to_dict() for candidate in result.candidates],
                        universe=universe,
                    ),
                )
        return {"asof": asof, "records": [r.to_dict() for r in records]}

    @app.get("/scan/tracking", dependencies=[Depends(require_auth)])
    async def scan_tracking_all(universe: str = "sp500") -> dict[str, Any]:
        """Return all tracking records across all scan dates."""
        records = load_all_tracking(universe=_validate_scan_universe(universe))
        return {"records": [r.to_dict() for r in records], "total": len(records)}

    @app.get("/scan/quintile", dependencies=[Depends(require_auth)])
    async def scan_quintile(
        universe: str = "hstech",
        period: str = "2022-2025",
        rebal_days: int = 21,
        cost_bps: int = 30,
        refined: bool = False,
        long_q: str = "Q2",
        short_q: str = "Q5",
    ) -> dict[str, Any]:
        """Run quintile-sort backtest for cross-sectional factor alpha.

        When ``refined=true``, each factor is first screened for quintile
        monotonicity; only those passing the threshold are kept for the
        composite backtest.
        """
        from src.scanner.manifest import load_factor_manifest
        from src.scanner.quintile import run_quintile_backtest
        from src.tools.alpha_bench_tool import _load_universe_panel

        cache_key = f"quintile:{universe}:{period}:{rebal_days}:{cost_bps}:{refined}:{long_q}:{short_q}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        loop = asyncio.get_running_loop()

        def _run():
            from src.factors.registry import Registry
            manifest = load_factor_manifest(universe=universe)
            panel = _load_universe_panel(universe, period)
            return run_quintile_backtest(
                panel=panel,
                factors=manifest.get("factors", []),
                registry=Registry(),
                rebal_days=rebal_days,
                cost_bps=cost_bps,
                refined=refined,
                long_q=long_q,
                short_q=short_q,
            )

        try:
            result = await loop.run_in_executor(None, _run)
            return _cache_set(cache_key, result.to_dict())
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/scan/quintile/walkforward", dependencies=[Depends(require_auth)])
    async def scan_walkforward(
        universe: str = "hstech",
        period: str = "2022-2025",
        rebal_days: int = 21,
        cost_bps: int = 30,
        long_q: str = "Q2",
        short_q: str = "Q5",
    ) -> dict[str, Any]:
        """Walk-forward OOS validation: screen factors in-sample, test out-of-sample."""
        from src.scanner.manifest import load_factor_manifest
        from src.scanner.quintile import run_walkforward_backtest
        from src.tools.alpha_bench_tool import _load_universe_panel

        cache_key = f"walkforward:{universe}:{period}:{rebal_days}:{cost_bps}:{long_q}:{short_q}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        loop = asyncio.get_running_loop()

        def _run():
            from src.factors.registry import Registry
            manifest = load_factor_manifest(universe=universe)
            panel = _load_universe_panel(universe, period)
            return run_walkforward_backtest(
                panel=panel,
                factors=manifest.get("factors", []),
                registry=Registry(),
                rebal_days=rebal_days,
                cost_bps=cost_bps,
                long_q=long_q,
                short_q=short_q,
            )

        try:
            result = await loop.run_in_executor(None, _run)
            return _cache_set(cache_key, result.to_dict())
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/scan/quintile/portfolio", dependencies=[Depends(require_auth)])
    async def scan_portfolio(
        universe: str = "hkconnect",
        period: str = "2024-2026",
    ) -> dict[str, Any]:
        """Current Q1 portfolio: screen factors on recent IS window, return holdings."""
        from src.scanner.manifest import load_factor_manifest
        from src.scanner.quintile import (
            N_QUANTILES, WF_IS_DAYS, WF_TOP_K, MONO_THRESHOLD,
            _compute_composite, _screen_on_window,
        )
        from src.tools.alpha_bench_tool import _load_universe_panel
        import pandas as pd

        cache_key = f"portfolio:{universe}:{period}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        loop = asyncio.get_running_loop()

        def _run():
            from src.factors.registry import Registry
            manifest = load_factor_manifest(universe=universe)
            factors = manifest.get("factors", [])
            panel = _load_universe_panel(universe, period)
            registry = Registry()
            close = panel["close"]
            n_rows = len(close)
            warmup = 60

            is_start = max(warmup, n_rows - WF_IS_DAYS)
            is_panel = {
                k: v.iloc[is_start:] for k, v in panel.items()
                if isinstance(v, pd.DataFrame)
            }
            for k, v in panel.items():
                if not isinstance(v, pd.DataFrame):
                    is_panel[k] = v

            kept = _screen_on_window(
                is_panel, factors, registry,
                rebal_days=21, warmup=warmup, threshold=MONO_THRESHOLD,
                top_k=WF_TOP_K,
            )
            if not kept:
                raise ValueError("no factors passed screening")

            composite = _compute_composite(kept, registry, panel, n_rows - 1, close)
            if composite is None or len(composite) < N_QUANTILES:
                raise ValueError("insufficient data for composite")

            labels = pd.qcut(composite, N_QUANTILES, labels=False, duplicates="drop")
            portfolio: dict[str, list[str]] = {}
            for q in range(N_QUANTILES):
                q_label = f"Q{N_QUANTILES - q}"
                symbols = sorted(labels[labels == q].index.tolist())
                portfolio[q_label] = symbols

            scores = composite.sort_values(ascending=False)
            q1_details = []
            for sym in portfolio.get("Q1", []):
                q1_details.append({"symbol": sym, "score": round(float(scores.get(sym, 0)), 4)})
            q1_details.sort(key=lambda x: x["score"], reverse=True)

            return {
                "universe": universe,
                "as_of": str(close.index[-1]),
                "n_stocks": len(close.columns),
                "n_factors_used": len(kept),
                "factors_used": [f["id"] for f in kept],
                "portfolio": {k: v for k, v in portfolio.items()},
                "q1_count": len(portfolio.get("Q1", [])),
                "q1_details": q1_details,
            }

        try:
            result = await loop.run_in_executor(None, _run)
            return _cache_set(cache_key, result)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/scan/accuracy", dependencies=[Depends(require_auth)])
    async def scan_accuracy(
        universe: str = "sp500", provider: str | None = None,
    ) -> dict[str, Any]:
        """Self-verification stats: forward-return means, hit rates, score
        quintile spread and IC per horizon, plus a per-date mean series.

        ``provider`` optionally restricts to one signal source (``factor_rank``
        / ``anomaly``)."""
        provider = provider or None
        if provider not in (None, "factor_rank", "anomaly"):
            raise HTTPException(status_code=400, detail="unknown provider filter")
        records = load_all_tracking(universe=_validate_scan_universe(universe))
        return {"universe": universe, "provider": provider,
                **compute_accuracy(records, provider=provider)}

    @app.get("/scan/calibration", dependencies=[Depends(require_auth)])
    async def scan_calibration(universe: str = "sp500") -> dict[str, Any]:
        """Run calibration check and return alerts."""
        records = load_all_tracking(universe=_validate_scan_universe(universe))
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
