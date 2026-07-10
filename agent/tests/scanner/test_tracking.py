"""Tests for scanner tracking: persistence, backfill, and calibration."""
from __future__ import annotations

import pandas as pd

from src.scanner.tracking import (
    TrackingRecord,
    _fetch_prices,
    backfill_returns,
    calibration_check,
    compute_accuracy,
    is_backfill_pending,
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

    def test_same_date_tracking_is_isolated_by_universe(self, tmp_path):
        save_tracking(
            [TrackingRecord(symbol="AAPL", score=80, asof="2025-06-01")],
            "2025-06-01", root=tmp_path, universe="sp500",
        )
        save_tracking(
            [TrackingRecord(symbol="0700.HK", score=90, asof="2025-06-01")],
            "2025-06-01", root=tmp_path, universe="hstech",
        )

        assert [r.symbol for r in load_tracking(
            "2025-06-01", root=tmp_path, universe="sp500"
        )] == ["AAPL"]
        assert [r.symbol for r in load_all_tracking(
            root=tmp_path, universe="hstech"
        )] == ["0700.HK"]

    def test_sp500_reads_legacy_tracking_path(self, tmp_path):
        legacy = tmp_path / "2025-06-01"
        legacy.mkdir()
        (legacy / "tracking.json").write_text(
            '[{"symbol":"AAPL","score":80,"asof":"2025-06-01"}]',
            encoding="utf-8",
        )

        assert [r.symbol for r in load_tracking(
            "2025-06-01", root=tmp_path, universe="sp500"
        )] == ["AAPL"]
        assert load_tracking("2025-06-01", root=tmp_path, universe="hstech") == []


class TestBackfillReturns:
    def test_fetch_prices_keeps_hk_suffix(self, monkeypatch):
        seen = []

        def fake_download(symbols, **kwargs):
            seen.extend(symbols)
            return pd.DataFrame()

        monkeypatch.setattr("src.scanner.tracking.yf.download", fake_download)

        _fetch_prices(["0700.HK", "AAPL.US"], "2025-06-02", "2025-06-10")

        assert seen == ["0700.HK", "AAPL"]

    def test_fetch_prices_zero_pads_short_hk_codes(self, monkeypatch):
        seen = []

        def fake_download(symbols, **kwargs):
            seen.extend(symbols)
            return pd.DataFrame()

        monkeypatch.setattr("src.scanner.tracking.yf.download", fake_download)

        _fetch_prices(["700.HK", "981.HK", "9626.HK"], "2025-06-02", "2025-06-10")

        assert seen == ["0700.HK", "0981.HK", "9626.HK"]

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
        def fetcher(syms, _start, _end):
            return self._make_price_df(syms)
        records = backfill_returns("2025-06-01", candidates, root=tmp_path,
                                   price_fetcher=fetcher)
        assert len(records) == 2
        aapl = next(r for r in records if r.symbol == "AAPL")
        assert aapl.entry_price is not None
        assert aapl.entry_date == "2025-06-02"
        assert aapl.fwd_1d is not None
        assert aapl.fwd_5d is not None
        assert aapl.fwd_10d is not None

    def test_backfill_empty_candidates(self, tmp_path):
        assert backfill_returns("2025-06-01", [], root=tmp_path) == []

    def test_backfill_persists(self, tmp_path):
        candidates = [{"symbol": "AAPL", "score": 90.0}]
        def fetcher(syms, _start, _end):
            return self._make_price_df(syms)
        backfill_returns("2025-06-01", candidates, root=tmp_path,
                         price_fetcher=fetcher)
        loaded = load_tracking("2025-06-01", root=tmp_path)
        assert len(loaded) == 1
        assert loaded[0].entry_price is not None


class TestIsBackfillPending:
    ASOF = "2025-06-02"  # a Monday

    def _record(self, **kwargs):
        return TrackingRecord(symbol="AAPL", score=90.0, asof=self.ASOF, **kwargs)

    def test_empty_records_not_pending(self):
        assert not is_backfill_pending([], self.ASOF, now="2025-07-01")

    def test_fresh_scan_not_pending(self):
        # Nothing can be filled on the signal date itself
        assert not is_backfill_pending([self._record()], self.ASOF, now=self.ASOF)

    def test_pending_when_fwd_1d_overdue(self):
        assert is_backfill_pending([self._record()], self.ASOF, now="2025-06-09")

    def test_pending_promptly_for_recent_missing_entry(self):
        # A 2-day-old scan whose entry/fwd_1d are still empty must be pending —
        # by T+2 the entry open and first close already exist (regression guard
        # against over-conservative pads that left recent dates unfilled).
        two_days = "2025-06-04"  # ASOF (Mon 06-02) + 2 calendar days
        assert is_backfill_pending([self._record()], self.ASOF, now=two_days)

    def test_not_pending_when_only_later_horizons_missing(self):
        rec = self._record(entry_date="2025-06-03", entry_price=100.0, fwd_1d=1.0)
        assert not is_backfill_pending([rec], self.ASOF, now="2025-06-09")

    def test_pending_when_fwd_5d_overdue(self):
        rec = self._record(entry_date="2025-06-03", entry_price=100.0, fwd_1d=1.0)
        assert is_backfill_pending([rec], self.ASOF, now="2025-06-16")

    def test_pending_when_fwd_20d_overdue(self):
        rec = self._record(entry_date="2025-06-03", entry_price=100.0,
                           fwd_1d=1.0, fwd_5d=2.0)
        assert is_backfill_pending([rec], self.ASOF, now="2025-07-10")

    def test_complete_records_not_pending(self):
        rec = self._record(entry_date="2025-06-03", entry_price=100.0,
                           fwd_1d=1.0, fwd_5d=2.0, fwd_10d=2.5, fwd_20d=3.0)
        assert not is_backfill_pending([rec], self.ASOF, now="2025-07-10")

    def test_pending_when_fwd_10d_overdue(self):
        # Legacy records saved before the 10d horizon existed must re-backfill.
        rec = self._record(entry_date="2025-06-03", entry_price=100.0,
                           fwd_1d=1.0, fwd_5d=2.0, fwd_20d=3.0)
        assert is_backfill_pending([rec], self.ASOF, now="2025-07-10")

    def test_not_pending_past_retry_window(self):
        # Delisted-style record that will never fill: stop retrying
        assert not is_backfill_pending([self._record()], self.ASOF, now="2025-09-01")

    def test_pending_when_any_record_incomplete(self):
        complete = self._record(entry_date="2025-06-03", entry_price=100.0,
                                fwd_1d=1.0, fwd_5d=2.0, fwd_20d=3.0)
        missing = TrackingRecord(symbol="GOOG", score=80.0, asof=self.ASOF,
                                 entry_date="2025-06-03", entry_price=100.0,
                                 fwd_1d=1.0, fwd_5d=2.0)
        assert is_backfill_pending([complete, missing], self.ASOF, now="2025-07-10")


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


class TestComputeAccuracy:
    def _recs(self):
        # scores 10..100; higher score → higher fwd_1d (positive IC/spread)
        return [
            TrackingRecord(symbol=f"S{i}", score=float(i * 10), asof="2025-06-02",
                           entry_price=100.0, fwd_1d=float(i - 3), fwd_5d=float(i))
            for i in range(1, 11)
        ]

    def test_empty(self):
        acc = compute_accuracy([])
        assert acc["total_tracked"] == 0
        assert acc["horizons"]["fwd_1d"] == {"n": 0}
        assert acc["timeseries"] == []

    def test_stats_and_positive_spread(self):
        acc = compute_accuracy(self._recs())
        h = acc["horizons"]["fwd_1d"]
        assert h["n"] == 10
        assert h["hit_rate"] == 70.0            # fwd_1d = i-3 > 0 for i=4..10
        assert h["spread"] > 0                  # top score quintile beats bottom
        assert h["ic"] > 0.9                     # monotonic score→return
        assert acc["horizons"]["fwd_20d"] == {"n": 0}

    def test_timeseries_grouped_by_date(self):
        recs = [
            TrackingRecord(symbol="A", score=50, asof="2025-06-02", fwd_1d=1.0),
            TrackingRecord(symbol="B", score=60, asof="2025-06-02", fwd_1d=3.0),
            TrackingRecord(symbol="C", score=70, asof="2025-06-03", fwd_1d=-2.0),
        ]
        ts = compute_accuracy(recs)["timeseries"]
        assert ts == [
            {"date": "2025-06-02", "n": 2, "mean_1d": 2.0},
            {"date": "2025-06-03", "n": 1, "mean_1d": -2.0},
        ]
