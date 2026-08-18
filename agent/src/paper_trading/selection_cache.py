"""Shared disk cache for annual robust-strategy selections.

One cache, two consumers: the forecast API surface (api_server) and the paper
auto-executor. Before this existed the executor recomputed the "annual"
selection from scratch every daily tick — slow (a full multi-window backtest
per symbol per day) and a dual-source risk: the executor could pick a
different strategy than the one the UI shows whenever a fresh computation
diverged from the API's year-cached pick. Both now read and write the same
files, so a selection cached by either surface is reused by the other.

File format matches the api_server originals (sha256(key) filename, payload
``{"created_at": ..., "result": ...}``) so existing cache entries stay valid.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".vibe-trading" / "cache" / "best_strategy"
SELECTION_TTL_SECONDS = 365 * 24 * 3600  # annual selection


def cache_path(key: str, cache_dir: Path | None = None) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return (cache_dir or DEFAULT_CACHE_DIR) / f"{digest}.json"


def selection_cache_key(market: str, display_code: str) -> str:
    """The selection cache key — must stay identical to api_server's."""
    from src.paper_trading.hstech_best import ROBUST_SELECTION_VERSION
    return f"forecast-robust-selection:{market.lower()}:{display_code}:{ROBUST_SELECTION_VERSION}"


def read_cache(key: str, ttl: float, cache_dir: Path | None = None) -> dict | None:
    path = cache_path(key, cache_dir)
    try:
        if time.time() - path.stat().st_mtime > ttl:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    result = payload.get("result") if isinstance(payload, dict) else None
    return result if isinstance(result, dict) else None


def write_cache(key: str, result: dict, cache_dir: Path | None = None) -> None:
    path = cache_path(key, cache_dir)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "result": result,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    except (OSError, TypeError, ValueError):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
