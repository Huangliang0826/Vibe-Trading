"""Tests for the universe-panel cache freshness rule (_cache_is_fresh).

A pickle written on day X can only contain data through X. Before this rule
existed, a cache whose period extended past its write date was reused
forever — the daily scanner scored on a three-week-old panel and produced
identical rankings day after day.
"""

from __future__ import annotations

import datetime as dt
import os

from src.tools.alpha_bench_tool import _cache_is_fresh


def _touch(path, day: dt.date) -> None:
    path.write_bytes(b"x")
    stamp = dt.datetime.combine(day, dt.time(12, 0)).timestamp()
    os.utime(path, (stamp, stamp))


def test_historical_period_stays_cached_forever(tmp_path) -> None:
    # Period ended before the file was written: content is complete.
    cache = tmp_path / "hstech_2022-01-01_2024-12-31.pkl"
    _touch(cache, dt.date(2025, 1, 15))
    assert _cache_is_fresh(cache, "2024-12-31") is True


def test_open_ended_period_written_today_is_fresh(tmp_path) -> None:
    cache = tmp_path / "hstech_2022-01-01_2026-12-31.pkl"
    _touch(cache, dt.date.today())
    assert _cache_is_fresh(cache, "2026-12-31") is True


def test_open_ended_period_written_earlier_is_stale(tmp_path) -> None:
    # The exact bug: period runs through year-end but the file predates today.
    cache = tmp_path / "hstech_2022-01-01_2026-12-31.pkl"
    _touch(cache, dt.date.today() - dt.timedelta(days=20))
    assert _cache_is_fresh(cache, "2026-12-31") is False


def test_period_ending_between_write_date_and_today_is_stale(tmp_path) -> None:
    # Written on the 1st, period ends on the 10th, today is later: the file
    # cannot contain the 2nd..10th — stale.
    written = dt.date.today() - dt.timedelta(days=20)
    end = dt.date.today() - dt.timedelta(days=10)
    cache = tmp_path / "sp500_2022-01-01_x.pkl"
    _touch(cache, written)
    assert _cache_is_fresh(cache, end.isoformat()) is False


def test_missing_file_is_stale(tmp_path) -> None:
    assert _cache_is_fresh(tmp_path / "nope.pkl", "2026-12-31") is False
