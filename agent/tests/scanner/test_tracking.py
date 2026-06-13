"""Tests for scanner tracking: persistence, backfill, and calibration."""
from __future__ import annotations

import pandas as pd
import pytest

from src.scanner.tracking import (
    CalibrationAlert,
    TrackingRecord,
    backfill_returns,
    calibration_check,
    load_all_tracking,
    load_tracking,
    save_tracking,
)


class TestTrackingRecord:
    def test_roundtrip(self):
        rec = TrackingRecord(
            symbol="AAPL", score=85.0, asof="2025-06-01",
            entry_date="2025-06-02", entry_price=190.0,
            fwd_1d=1.5, fwd_5d=3.2, fwd_20d=-0.8,
        )
        d = rec.to_dict()
        restored = TrackingRecord.from_dict(d)
        assert restored.symbol == rec.symbol
        assert restored.score == rec.score
        assert restored.fwd_5d == rec.fwd_5d

    def test_to_dict_omits_none(self):
        rec = TrackingRecord(symbol="MSFT", score=70.0, asof="2025-06-01")
        d = rec.to_dict()
        assert "entry_price" not in d
        assert "fwd_1d" not in d


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        records = [
            TrackingRecord(symbol="AAPL", score=90.0, asof="2025-06-01",
                           entry_price=190.0, fwd_1d=1.0),
            TrackingRecord(symbol="GOOG", score=80.0, asof="2025-06-01"),
        ]
        save_tracking(records, "2025-06-01", root=tmp_path)
        loaded = load_tracking("2025-06-01", root=tmp_path)
        assert len(loaded) == 2
        assert loaded[0].symbol == "AAPL"
        assert loaded[0].fwd_1d == 1.0

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_tracking("2099-01-01", root=tmp_path) == []

    def test_load_all(self, tmp_path):
        save_tracking(
            [TrackingRecord(symbol="A", score=50, asof="2025-06-01")],
            "2025-06-01", root=tmp_path,
        )
        save_tracking(
            [TrackingRecord(symbol="B", score=60, asof="2025-06-02")],
            "2025-06-02", root=tmp_path,
        )
        all_recs = load_all_tracking(root=tmp_path)
        assert len(all_recs) == 2
        assert {r.symbol for r in all_recs} == {"A", "B"}


class TestBackfillReturns:
    def _make_price_df(self, symbols, n_days=25):
        """Create a fake price DataFrame mimicking yfinance output."""
        dates = pd.bdate_range("2025-06-02", periods=n_days)
        if len(symbols) == 1:
            sym = symbols[0]
            data = {
                "Open": [100.0 + i * 0.5 for i in range(n_days)],
                "Close": [100.5 + i * 0.5 for i in range(n_days)],
            }
            return pd.DataFrame(data, index=dates)
        else:
            arrays = [[], []]
            data = {}
            for sym in symbols:
                for col in ["Open", "Close"]:
                    arrays[0].append(col)
                    arrays[1].append(sym)
            idx = pd.MultiIndex.from_arrays(arrays)
            vals = {}
            for i, sym in enumerate(symbols):
                base = 100.0 + i * 50
                vals[("Open", sym)] = [base + j * 0.5 for j in range(n_days)]
                vals[("Close", sym)] = [base + 0.5 + j * 0.5 for j in range(n_days)]
            return pd.DataFrame(vals, index=dates)

    def test_backfill_computes_returns(self, tmp_path):
        candidates = [
            {"symbol": "AAPL", "score": 90.0},
            {"symbol": "GOOG", "score": 80.0},
        ]
        fetcher = lambda syms, s, e: self._make_price_df(syms)
        records = backfill_returns("2025-06-01", candidates, root=tmp_path,
                                   price_fetcher=fetcher)
        assert len(records) == 2
        aapl = next(r for r in records if r.symbol == "AAPL")
        assert aapl.entry_price is not None
        assert aapl.entry_date == "2025-06-02"
        assert aapl.fwd_1d is not None
        assert aapl.fwd_5d is not None

    def test_backfill_empty_candidates(self, tmp_path):
        assert backfill_returns("2025-06-01", [], root=tmp_path) == []

    def test_backfill_persists(self, tmp_path):
        candidates = [{"symbol": "AAPL", "score": 90.0}]
        fetcher = lambda syms, s, e: self._make_price_df(syms)
        backfill_returns("2025-06-01", candidates, root=tmp_path,
                         price_fetcher=fetcher)
        loaded = load_tracking("2025-06-01", root=tmp_path)
        assert len(loaded) == 1
        assert loaded[0].entry_price is not None


class TestCalibrationCheck:
    def _make_records(self, n, score_fn, return_fn):
        """Generate n records with controllable score/return functions."""
        return [
            TrackingRecord(
                symbol=f"SYM{i}", score=score_fn(i), asof="2025-01-01",
                entry_price=100.0, fwd_5d=return_fn(i),
            )
            for i in range(n)
        ]

    def test_no_alert_when_too_few_samples(self):
        records = self._make_records(50, lambda i: 80 - i, lambda i: 2.0 - i * 0.05)
        alerts = calibration_check(records, min_samples=100)
        assert alerts == []

    def test_no_alert_when_calibrated(self):
        # High-score stocks have positive returns, low-score have negative
        records = self._make_records(
            200,
            score_fn=lambda i: 100 - i * 0.5,
            return_fn=lambda i: 5.0 - i * 0.05,
        )
        alerts = calibration_check(records, threshold_pp=8.0, min_samples=100)
        assert alerts == []

    def test_alert_when_inverted(self):
        # High-score stocks have bad returns, low-score have good ones
        records = self._make_records(
            200,
            score_fn=lambda i: 100 - i * 0.5,
            return_fn=lambda i: -10.0 + i * 0.1,
        )
        alerts = calibration_check(records, threshold_pp=8.0, min_samples=100)
        assert len(alerts) >= 1
        assert any(a.metric == "quintile_spread_5d" for a in alerts)

    def test_alert_when_overall_negative(self):
        records = self._make_records(
            200,
            score_fn=lambda i: 80.0,
            return_fn=lambda i: -12.0,
        )
        alerts = calibration_check(records, threshold_pp=8.0, min_samples=100)
        assert any(a.metric == "overall_mean_5d" for a in alerts)
