"""Daily paper-tick scheduler due-logic (Phase 2c)."""
from __future__ import annotations

from datetime import datetime

from src.paper_trading.schedule import MARKET_TZ, is_due


def _et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=MARKET_TZ)


def test_due_on_a_weekday_after_run_time_when_enabled_and_not_yet_run():
    # Wed 2026-08-05, 10:01 ET
    assert is_due(_et(2026, 8, 5, 10, 1), {"enabled": True, "last_run_date": None}) is True


def test_not_due_when_disabled():
    assert is_due(_et(2026, 8, 5, 10, 1), {"enabled": False, "last_run_date": None}) is False


def test_not_due_before_run_time():
    assert is_due(_et(2026, 8, 5, 9, 45), {"enabled": True, "last_run_date": None}) is False


def test_not_due_on_weekend():
    # Sat 2026-08-08
    assert is_due(_et(2026, 8, 8, 11, 0), {"enabled": True, "last_run_date": None}) is False


def test_not_due_twice_the_same_day():
    assert is_due(_et(2026, 8, 5, 15, 0), {"enabled": True, "last_run_date": "2026-08-05"}) is False


def test_due_again_the_next_day():
    assert is_due(_et(2026, 8, 6, 10, 5), {"enabled": True, "last_run_date": "2026-08-05"}) is True
