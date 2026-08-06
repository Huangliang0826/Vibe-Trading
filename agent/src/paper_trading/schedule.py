"""Persisted state + due logic for the daily paper-tick scheduler (Phase 2c).

Runs the deterministic paper executor once per US trading day, shortly after the
open. Two-key safety model: the schedule must be explicitly ``enabled`` here AND
the global kill switch must be resumed for any order to actually be placed — the
executor still gates execution on the kill switch.

The due logic is pure/testable (weekday + time-of-day + once-per-day + enabled);
the holiday gate (is the market actually open today) is applied by the caller via
the broker clock, since it needs I/O.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

from src.config.paths import get_runtime_root

MARKET_TZ = ZoneInfo("America/New_York")
# Fire after the 09:30 ET open — 10:00 ET lets the opening print settle.
RUN_AFTER = time(10, 0)


def _path():
    return get_runtime_root() / "live" / "paper" / "schedule.json"


def read_schedule() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return {"enabled": bool(data.get("enabled")), "last_run_date": data.get("last_run_date")}
    except (OSError, ValueError):
        return {"enabled": False, "last_run_date": None}


def write_schedule(state: dict) -> dict:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {"enabled": bool(state.get("enabled")), "last_run_date": state.get("last_run_date")}
    path.write_text(json.dumps(clean) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return clean


def set_enabled(enabled: bool) -> dict:
    state = read_schedule()
    state["enabled"] = bool(enabled)
    return write_schedule(state)


def mark_ran(date_iso: str) -> dict:
    state = read_schedule()
    state["last_run_date"] = date_iso
    return write_schedule(state)


def et_now() -> datetime:
    return datetime.now(MARKET_TZ)


def is_due(now_et: datetime, state: dict) -> bool:
    """Whether a scheduled tick is due (pure — no market-holiday I/O)."""
    if not state.get("enabled"):
        return False
    if now_et.weekday() >= 5:  # Sat/Sun
        return False
    if now_et.timetz().replace(tzinfo=None) < RUN_AFTER:
        return False
    if state.get("last_run_date") == now_et.date().isoformat():
        return False
    return True
