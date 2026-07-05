from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import api_server


class _DateFilteringLoader:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls: list[tuple[str, str, str]] = []

    def fetch(self, *, codes, start_date, end_date, interval):
        self.calls.append((start_date, end_date, interval))
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        selected = self.frame.loc[(self.frame.index >= start) & (self.frame.index <= end)]
        return {codes[0]: selected.copy()}


def _daily_frame(start: date, end: date) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="B")
    return pd.DataFrame(
        {
            "close": range(100, 100 + len(index)),
            "volume": [1_000] * len(index),
        },
        index=index,
    )


def _install_loader(monkeypatch, frame: pd.DataFrame) -> _DateFilteringLoader:
    loader = _DateFilteringLoader(frame)
    monkeypatch.setattr("backtest.loaders.registry.resolve_loader", lambda _market: loader)
    monkeypatch.setattr(api_server, "_resolve_symbol_name", lambda _code, _market: "Test")
    return loader


def _previous_business_day(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def test_one_year_history_starts_at_exact_calendar_boundary(monkeypatch):
    today = date.today()
    frame = _daily_frame(today - timedelta(days=500), today)
    loader = _install_loader(monkeypatch, frame)

    result = api_server._fetch_price_history("NVDA", "1Y", "us")

    target = api_server._price_period_baseline_date("1Y", today)
    assert result["bars"][0]["date"] == _previous_business_day(target).isoformat()
    assert loader.calls[-1][1] == today.isoformat()


def test_ytd_history_includes_previous_year_final_close(monkeypatch):
    today = date.today()
    frame = _daily_frame(date(today.year - 1, 12, 1), today)
    _install_loader(monkeypatch, frame)

    result = api_server._fetch_price_history("NVDA", "YTD", "us")

    target = date(today.year - 1, 12, 31)
    assert result["bars"][0]["date"] == _previous_business_day(target).isoformat()


def test_all_history_keeps_the_earliest_available_bar(monkeypatch):
    today = date.today()
    frame = _daily_frame(date(2000, 1, 3), today)
    _install_loader(monkeypatch, frame)

    result = api_server._fetch_price_history("NVDA", "ALL", "us")

    assert len(result["bars"]) == len(frame)
    assert result["bars"][0]["date"] == "2000-01-03"
