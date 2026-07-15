"""Tests for the event-driven scanner provider."""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pandas as pd

from src.scanner.providers.event import (
    EventProvider,
    _analyst_upgrades,
    _earnings_proximity,
    _insider_net_buys,
    _score_analyst,
    _score_earnings,
    _score_insider,
)


# ── scoring functions ────────────────────────────────────────────────────────

class TestScoreEarnings:
    def test_zero_days(self):
        assert _score_earnings(0) == 100.0

    def test_seven_days(self):
        assert 45 < _score_earnings(7) < 55

    def test_fourteen_days(self):
        assert _score_earnings(14) == 0.0

    def test_beyond_horizon(self):
        assert _score_earnings(30) == 0.0

    def test_negative_days(self):
        assert _score_earnings(-1) == 0.0


class TestScoreInsider:
    def test_no_net_buys(self):
        assert _score_insider({"net_count": 0, "net_value": 0}) == 0.0

    def test_net_sells(self):
        assert _score_insider({"net_count": -2, "net_value": -1000000}) == 0.0

    def test_small_buy(self):
        score = _score_insider({"net_count": 1, "net_value": 100000})
        assert 10 < score < 20

    def test_large_buy(self):
        score = _score_insider({"net_count": 5, "net_value": 5000000})
        assert score == 100.0


class TestScoreAnalyst:
    def test_no_activity(self):
        assert _score_analyst({"upgrades": 0, "downgrades": 0, "total": 0}) == 0.0

    def test_net_downgrade(self):
        assert _score_analyst({"upgrades": 1, "downgrades": 2, "total": 3}) == 0.0

    def test_net_upgrade(self):
        score = _score_analyst({"upgrades": 2, "downgrades": 0, "total": 5})
        assert score > 50


# ── signal extraction (mocked yfinance) ──────────────────────────────────────

class TestEarningsProximity:
    def test_upcoming_earnings(self):
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [dt.date(2026, 7, 1)]}
        days = _earnings_proximity(ticker, dt.date(2026, 6, 25))
        assert days == 6

    def test_no_future_earnings(self):
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [dt.date(2026, 1, 1)]}
        result = _earnings_proximity(ticker, dt.date(2026, 6, 25))
        assert result is None

    def test_no_calendar(self):
        ticker = MagicMock()
        ticker.calendar = {}
        assert _earnings_proximity(ticker, dt.date(2026, 6, 25)) is None

    def test_exception(self):
        ticker = MagicMock()
        ticker.calendar = property(lambda self: (_ for _ in ()).throw(Exception("fail")))
        type(ticker).calendar = property(lambda self: (_ for _ in ()).throw(Exception()))
        assert _earnings_proximity(ticker, dt.date(2026, 6, 25)) is None


class TestInsiderNetBuys:
    def test_recent_purchases(self):
        ticker = MagicMock()
        ticker.insider_transactions = pd.DataFrame({
            "Shares": [1000, 500],
            "Value": [100000.0, 50000.0],
            "Transaction": ["Purchase", "Sale"],
            "Start Date": ["2026-06-10", "2026-06-15"],
        })
        result = _insider_net_buys(ticker, dt.date(2026, 6, 20))
        assert result is not None
        assert result["buy_count"] == 1
        assert result["sell_count"] == 1
        assert result["net_count"] == 0

    def test_no_transactions(self):
        ticker = MagicMock()
        ticker.insider_transactions = pd.DataFrame()
        assert _insider_net_buys(ticker, dt.date(2026, 6, 20)) is None

    def test_old_transactions_filtered(self):
        ticker = MagicMock()
        ticker.insider_transactions = pd.DataFrame({
            "Shares": [1000],
            "Value": [100000.0],
            "Transaction": ["Purchase"],
            "Start Date": ["2025-01-01"],
        })
        result = _insider_net_buys(ticker, dt.date(2026, 6, 20))
        assert result is None


class TestAnalystUpgrades:
    def test_recent_upgrades(self):
        ticker = MagicMock()
        idx = pd.to_datetime(["2026-06-10", "2026-06-15"])
        ud = pd.DataFrame({
            "Firm": ["Goldman", "Morgan"],
            "Action": ["upgrade", "downgrade"],
            "ToGrade": ["Buy", "Sell"],
            "FromGrade": ["Hold", "Buy"],
        }, index=idx)
        ud.index.name = "GradeDate"
        ticker.upgrades_downgrades = ud
        result = _analyst_upgrades(ticker, dt.date(2026, 6, 20))
        assert result is not None
        assert result["upgrades"] == 1
        assert result["downgrades"] == 1

    def test_no_data(self):
        ticker = MagicMock()
        ticker.upgrades_downgrades = None
        assert _analyst_upgrades(ticker, dt.date(2026, 6, 20)) is None


# ── provider integration ─────────────────────────────────────────────────────

class TestEventProvider:
    def _make_panel(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        dates = pd.date_range("2026-05-01", "2026-06-19", freq="B")
        close = pd.DataFrame(
            {s: range(100, 100 + len(dates)) for s in symbols},
            index=dates,
        )
        return {"close": close}

    @patch("src.scanner.providers.event.yf.Ticker")
    def test_earnings_detected(self, mock_ticker_cls):
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [dt.date(2026, 6, 22)]}
        ticker.insider_transactions = None
        ticker.upgrades_downgrades = None
        mock_ticker_cls.return_value = ticker

        provider = EventProvider(top_n=10, min_score=5.0)
        panel = self._make_panel(["AAPL.US"])
        results = provider.compute(panel, "2026-06-19")

        assert len(results) >= 1
        assert results[0].symbol == "AAPL.US"
        assert results[0].provider_id == "event"
        assert "财报临近" in results[0].attribution

    @patch("src.scanner.providers.event.yf.Ticker")
    def test_no_events(self, mock_ticker_cls):
        ticker = MagicMock()
        ticker.calendar = {}
        ticker.insider_transactions = None
        ticker.upgrades_downgrades = None
        mock_ticker_cls.return_value = ticker

        provider = EventProvider(top_n=10)
        panel = self._make_panel(["AAPL.US"])
        results = provider.compute(panel, "2026-06-19")
        assert len(results) == 0

    @patch("src.scanner.providers.event.yf.Ticker")
    def test_min_score_filter(self, mock_ticker_cls):
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [dt.date(2026, 6, 30)]}
        ticker.insider_transactions = None
        ticker.upgrades_downgrades = None
        mock_ticker_cls.return_value = ticker

        provider = EventProvider(top_n=10, min_score=90.0)
        panel = self._make_panel(["AAPL.US"])
        results = provider.compute(panel, "2026-06-19")
        assert len(results) == 0

    @patch("src.scanner.providers.event.yf.Ticker")
    def test_top_n_limit(self, mock_ticker_cls):
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [dt.date(2026, 6, 20)]}
        ticker.insider_transactions = None
        ticker.upgrades_downgrades = None
        mock_ticker_cls.return_value = ticker

        symbols = [f"SYM{i}.US" for i in range(10)]
        provider = EventProvider(top_n=3, min_score=5.0)
        panel = self._make_panel(symbols)
        results = provider.compute(panel, "2026-06-19")
        assert len(results) <= 3

    @patch("src.scanner.providers.event.yf.Ticker")
    def test_chinese_labels(self, mock_ticker_cls):
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [dt.date(2026, 6, 20)]}
        idx = pd.to_datetime(["2026-06-15"])
        ud = pd.DataFrame({
            "Firm": ["GS"],
            "Action": ["upgrade"],
            "ToGrade": ["Buy"],
            "FromGrade": ["Hold"],
        }, index=idx)
        ud.index.name = "GradeDate"
        ticker.upgrades_downgrades = ud
        ticker.insider_transactions = None
        mock_ticker_cls.return_value = ticker

        provider = EventProvider(top_n=10, min_score=5.0)
        panel = self._make_panel(["AAPL.US"])
        results = provider.compute(panel, "2026-06-19")
        assert len(results) >= 1
        detail_keys = set(results[0].detail.keys())
        assert detail_keys.issubset({"财报临近", "内部人买入", "分析师调升"})

    def test_empty_panel(self):
        provider = EventProvider()
        results = provider.compute({"close": pd.DataFrame()}, "2026-06-19")
        assert results == []
