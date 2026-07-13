"""Tests for the data-quality sentinel's pure checks."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data_quality.sentinel import (
    check_adj_ratio,
    check_bad_values,
    check_gaps,
    check_price_jumps,
    check_staleness,
    run_symbol_checks,
)


def _frame(closes, adj=None, start="2026-01-05", symbol="TEST") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes))
    frame = pd.DataFrame({
        "close": np.asarray(closes, dtype=float),
        "adj_close": np.asarray(adj if adj is not None else closes, dtype=float),
    }, index=idx)
    frame.attrs["symbol"] = symbol
    return frame


def _healthy(n=120, start="2026-01-05") -> pd.DataFrame:
    closes = [100 * (1 + 0.001 * i) for i in range(n)]
    return _frame(closes, start=start)


class TestStaleness:
    def test_fresh_series_passes(self) -> None:
        frame = _healthy()
        asof = pd.Timestamp(frame.index.max())
        assert check_staleness(frame, asof) == []

    def test_stale_series_alerts(self) -> None:
        frame = _healthy()
        asof = pd.Timestamp(frame.index.max()) + pd.Timedelta(days=10)
        findings = check_staleness(frame, asof)
        assert len(findings) == 1
        assert findings[0].severity == "ALERT"
        assert findings[0].check == "staleness"

    def test_weekend_lag_tolerated(self) -> None:
        # Friday bar checked on Monday = 1 business day of lag.
        frame = _healthy()
        asof = pd.Timestamp(frame.index.max()) + pd.Timedelta(days=3)
        assert check_staleness(frame, asof) == []

    def test_empty_series_alerts(self) -> None:
        frame = pd.DataFrame()
        frame.attrs["symbol"] = "EMPTY"
        findings = check_staleness(frame, pd.Timestamp("2026-07-13"))
        assert findings and findings[0].severity == "ALERT"


class TestGaps:
    def test_contiguous_series_passes(self) -> None:
        assert check_gaps(_healthy()) == []

    def test_long_hole_alerts(self) -> None:
        frame = _healthy(60)
        holed = pd.concat([frame.iloc[:20], frame.iloc[40:]])
        holed.attrs["symbol"] = "TEST"
        findings = check_gaps(holed)
        assert len(findings) == 1
        assert findings[0].check == "calendar_gap"

    def test_short_holiday_gap_tolerated(self) -> None:
        frame = _healthy(60)
        holed = pd.concat([frame.iloc[:20], frame.iloc[23:]])  # 3-bday hole
        holed.attrs["symbol"] = "TEST"
        assert check_gaps(holed) == []


class TestPriceJumps:
    def test_unapplied_split_artifact_alerts(self) -> None:
        # Raw close halves overnight (2:1 split) while adj stays smooth.
        closes = [100.0] * 30 + [50.0] * 30
        adj = [50.0] * 60
        findings = check_price_jumps(_frame(closes, adj))
        assert any(f.check == "split_artifact" and f.severity == "ALERT" for f in findings)

    def test_real_crash_moves_both_series(self) -> None:
        # Both series fall together → not a split artifact; extreme-move WARN.
        closes = [100.0] * 30 + [50.0] * 30
        findings = check_price_jumps(_frame(closes, closes))
        assert not any(f.check == "split_artifact" for f in findings)
        assert any(f.check == "extreme_move" and f.severity == "WARN" for f in findings)

    def test_normal_volatility_passes(self) -> None:
        assert check_price_jumps(_healthy()) == []


class TestAdjRatio:
    def test_dividend_history_passes(self) -> None:
        # One dividend adjustment step, latest ratio = 1: healthy.
        closes = [100.0] * 60
        adj = [99.0] * 30 + [100.0] * 30
        assert check_adj_ratio(_frame(closes, adj)) == []

    def test_baseline_off_alerts(self) -> None:
        # Latest adj/close far from 1 → modules disagree on today's price.
        closes = [100.0] * 60
        adj = [90.0] * 60
        findings = check_adj_ratio(_frame(closes, adj))
        assert any(f.check == "adj_baseline" and f.severity == "ALERT" for f in findings)

    def test_adj_above_close_warns(self) -> None:
        closes = [100.0] * 59 + [100.0]
        adj = [110.0] * 59 + [100.0]
        findings = check_adj_ratio(_frame(closes, adj))
        assert any(f.check == "adj_above_close" and f.severity == "WARN" for f in findings)

    def test_ratio_churn_alerts(self) -> None:
        # Adjustment factor flapping on ~30 days → unstable adjustments.
        closes = [100.0] * 60
        adj = [100.0 if i % 2 else 99.0 for i in range(59)] + [100.0]
        findings = check_adj_ratio(_frame(closes, adj))
        assert any(f.check == "adj_churn" and f.severity == "ALERT" for f in findings)


class TestBadValues:
    def test_clean_series_passes(self) -> None:
        assert check_bad_values(_healthy()) == []

    def test_zero_close_alerts(self) -> None:
        closes = [100.0] * 55 + [0.0] + [100.0] * 4
        findings = check_bad_values(_frame(closes))
        assert findings and findings[0].check == "bad_values"

    def test_old_bad_value_outside_window_ignored(self) -> None:
        closes = [0.0] + [100.0] * 99
        assert check_bad_values(_frame(closes)) == []


def test_healthy_series_has_no_findings_end_to_end() -> None:
    frame = _healthy()
    asof = pd.Timestamp(frame.index.max())
    assert run_symbol_checks(frame, asof) == []
