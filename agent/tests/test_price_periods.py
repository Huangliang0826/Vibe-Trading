"""Price-history period boundaries, including the added 3M/6M/2Y/4Y."""
from __future__ import annotations

import datetime as dt

import pytest

import api_server


@pytest.mark.parametrize("period,expected", [
    ("1M", dt.date(2026, 7, 26)),
    ("3M", dt.date(2026, 5, 26)),
    ("6M", dt.date(2026, 2, 26)),
    ("YTD", dt.date(2025, 12, 31)),
    ("1Y", dt.date(2025, 8, 26)),
    ("2Y", dt.date(2024, 8, 26)),
    ("3Y", dt.date(2023, 8, 26)),
    ("4Y", dt.date(2022, 8, 26)),
    ("5Y", dt.date(2021, 8, 26)),
])
def test_period_baselines(period, expected):
    assert api_server._price_period_baseline_date(period, dt.date(2026, 8, 26)) == expected


def test_month_periods_cross_the_year_boundary():
    # 3 months before February lands in the previous November.
    assert api_server._price_period_baseline_date("3M", dt.date(2026, 2, 15)) == dt.date(2025, 11, 15)
    assert api_server._price_period_baseline_date("6M", dt.date(2026, 1, 10)) == dt.date(2025, 7, 10)


def test_month_periods_clamp_to_a_shorter_target_month():
    # 31 May minus 3 months has no 31st in February.
    assert api_server._price_period_baseline_date("3M", dt.date(2026, 5, 31)) == dt.date(2026, 2, 28)


def test_leap_day_year_periods_clamp():
    assert api_server._price_period_baseline_date("2Y", dt.date(2024, 2, 29)) == dt.date(2022, 2, 28)


def test_all_and_unknown_periods_have_no_baseline():
    assert api_server._price_period_baseline_date("ALL", dt.date(2026, 8, 26)) is None
    assert api_server._price_period_baseline_date("7Y", dt.date(2026, 8, 26)) is None
