"""Run the existing scanner/news batch once on the first daily startup."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config.paths import get_runtime_root
from src.scanner.schedule import DEFAULT_UNIVERSES, run_daily

log = logging.getLogger(__name__)

DEFAULT_STATE_PATH = get_runtime_root() / "daily-startup-refresh.json"
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
_startup_task: asyncio.Task[bool] | None = None


def run_startup_refresh_once(
    *, state_path: Path | None = None, today: dt.date | None = None,
) -> bool:
    """Trigger the daily scanner/news batch once per Amsterdam calendar day."""
    marker = state_path or DEFAULT_STATE_PATH
    current = today or dt.datetime.now(AMSTERDAM).date()
    date_key = current.isoformat()

    try:
        saved = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        saved = {}
    if saved.get("date") == date_key:
        log.info("daily startup refresh already triggered for %s", date_key)
        return False

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"date": date_key}) + "\n", encoding="utf-8")
    log.info("starting daily scanner and news refresh for %s", date_key)
    try:
        run_daily(DEFAULT_UNIVERSES)
    except Exception as exc:  # noqa: BLE001 - startup refresh must never stop the API
        log.exception("daily startup refresh failed: %s", exc)
    return True


def schedule_startup_refresh() -> asyncio.Task[bool]:
    """Schedule the blocking refresh helper without delaying API startup."""
    global _startup_task
    _startup_task = asyncio.create_task(asyncio.to_thread(run_startup_refresh_once))
    return _startup_task
