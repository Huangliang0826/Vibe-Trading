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
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.config.paths import get_runtime_root

MARKET_TZ = ZoneInfo("America/New_York")
# Fire after the 09:30 ET open — 10:00 ET lets the opening print settle.
RUN_AFTER = time(10, 0)
# US regular-session close. Before it, today's daily bar is still a live,
# moving print — anything computed from it is not reproducible.
MARKET_CLOSE = time(16, 0)


def last_settled_session(now_et: datetime) -> date:
    """Most recent trading day whose daily bar is final.

    Weekend- and close-time aware only; there is no holiday calendar here. On the
    day after a holiday this can name the holiday itself, which is harmless: the
    date is used as an inclusive upper bound, so a day with no bar just yields
    the previous one.
    """
    day = now_et.date()
    if day.weekday() < 5 and now_et.timetz().replace(tzinfo=None) < MARKET_CLOSE:
        day -= timedelta(days=1)  # today's bar is still moving
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


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
