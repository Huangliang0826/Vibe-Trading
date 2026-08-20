"""Daily warm-up marker for the forecast page caches.

The forecast cone is expensive (a TimesFM inference per symbol, ~7s cold) and
its cache key embeds the trading date, so every symbol goes cold at midnight
and the first visitor of the day pays the full cost for the whole watchlist.

This module owns only the "has today's warm-up already run?" marker; the actual
warming lives in the API layer, which calls the real endpoint functions so the
warmed entries land under exactly the keys the page will ask for.

The marker uses the LOCAL calendar date on purpose: the forecast caches key on
``default_end_date()`` (also local), so both roll over together.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from src.config.paths import get_runtime_root

log = logging.getLogger(__name__)

DEFAULT_STATE_PATH = get_runtime_root() / "forecast-warmup.json"


def _state_path(state_path: Path | None = None) -> Path:
    return state_path or DEFAULT_STATE_PATH


def read_marker(state_path: Path | None = None) -> dict:
    """Return the persisted warm-up marker ({} when absent/corrupt)."""
    try:
        data = json.loads(_state_path(state_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def needs_warmup(*, state_path: Path | None = None, today: dt.date | None = None) -> bool:
    """Whether today's warm-up still has to run."""
    current = (today or dt.date.today()).isoformat()
    return read_marker(state_path).get("date") != current


def mark_warmed(
    *,
    state_path: Path | None = None,
    today: dt.date | None = None,
    warmed: int = 0,
    failed: int = 0,
) -> dict:
    """Record that today's warm-up completed."""
    marker = _state_path(state_path)
    payload = {
        "date": (today or dt.date.today()).isoformat(),
        "warmed": int(warmed),
        "failed": int(failed),
        "finished_at": dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    except OSError as exc:  # a marker failure must never break warming
        log.warning("forecast warm-up marker write failed: %s", exc)
    return payload
