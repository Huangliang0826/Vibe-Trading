"""Factor whitelist: factors that pass strict bench (t>=3.0) on the universe.

The whitelist is a slow-to-build artifact (strict bench is minutes-to-hours),
refreshed manually via ``scan validate --refresh-factors`` and read cheaply on
every scan.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# Default threshold is 3.0, deliberately stricter than bench's back-compat 2.0
# (Harvey-Liu-Zhu territory) to keep false factors out of the leaderboard.
DEFAULT_THRESHOLD = 3.0

StrictRunner = Callable[..., dict[str, Any]]


def default_manifest_path() -> Path:
    return Path.home() / ".vibe-trading" / "scans" / "factor_whitelist.json"


def build_factor_manifest(
    zoos: Iterable[str],
    universe: str,
    period: str,
    out_path: Path | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    runner: StrictRunner | None = None,
) -> dict[str, Any]:
    """Run strict bench per zoo, keep alive passers, write + return the manifest.

    Args:
        zoos: Zoo ids to bench (e.g. ``["gtja191", "alpha101"]``).
        universe: Universe key (``sp500``).
        period: Bench window, ``YYYY-YYYY`` or ISO range.
        out_path: Destination JSON; defaults to ``default_manifest_path()``.
        threshold: ``alpha_t`` cutoff; factors below are dropped.
        runner: Injectable strict-bench callable (defaults to the real one).

    Returns:
        The manifest dict (also written to disk).
    """
    if runner is None:
        from src.factors.bench_runner_strict import run_bench_strict as runner  # type: ignore

    out = Path(out_path) if out_path is not None else default_manifest_path()
    kept: list[dict[str, Any]] = []
    for zoo in zoos:
        res = runner(zoo, universe, period, alpha_t_threshold=threshold)
        for row in res.get("rows", []):
            if row.get("category") == "alive" and float(row.get("alpha_t", 0.0)) >= threshold:
                kept.append({
                    "id": str(row["id"]),
                    "zoo": str(row.get("zoo", zoo)),
                    "ir": round(float(row.get("ir", 0.0)), 4),
                    "alpha_t": round(float(row.get("alpha_t", 0.0)), 3),
                })

    manifest = {
        "universe": universe,
        "period": period,
        "threshold": threshold,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "factors": kept,
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    return manifest


def load_factor_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load the manifest, with an actionable error when it's absent."""
    p = Path(path) if path is not None else default_manifest_path()
    if not p.is_file():
        raise FileNotFoundError(
            f"factor whitelist not found at {p}; build it with "
            "'vibe-trading scan validate --refresh-factors'"
        )
    return json.loads(p.read_text(encoding="utf-8"))
