"""Tests for the anomaly detection provider."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.scanner.providers.anomaly import (
    AnomalyProvider,
    _gap_magnitude,
    _range_expansion,
    _volatility_contraction,
    _volume_spike,
    _volume_trend,
)


def _make_series(values: list[float], start: str = "2025-01-01") -> pd.Series:
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx)


class TestVolumeSpike:
    def test_normal_volume(self):
        vals = [100.0] * 21
        assert _volume_spike(_make_series(vals)) == pytest.approx(1.0)

    def test_spike(self):
        vals = [100.0] * 20 + [400.0]
        result = _volume_spike(_make_series(vals))
        assert result is not None
        assert result == pytest.approx(4.0)

    def test_insufficient_data(self):
        assert _volume_spike(_make_series([100.0] * 5)) is None


class TestVolumeTrend:
    def test_flat(self):
        vals = [100.0] * 20
        result = _volume_trend(_make_series(vals))
        assert result == pytest.approx(1.0)

    def test_rising(self):
        vals = [100.0] * 15 + [200.0] * 5
        result = _volume_trend(_make_series(vals))
        assert result is not None
        assert result > 1.0


class TestVolatilityContraction:
    def test_contraction(self):
        n = 30
        high = _make_series([110.0] * 25 + [102.0] * 5)
        low = _make_series([90.0] * 25 + [98.0] * 5)
        close = _make_series([100.0] * n)
        result = _volatility_contraction(high, low, close)
        assert result is not None
        assert result < 0.5

    def test_expansion(self):
        n = 30
        high = _make_series([102.0] * 25 + [120.0] * 5)
        low = _make_series([98.0] * 25 + [80.0] * 5)
        close = _make_series([100.0] * n)
        result = _volatility_contraction(high, low, close)
        assert result is not None
        assert result > 1.5


class TestGapMagnitude:
    def test_no_gap(self):
        close = _make_series([100.0, 100.0, 100.0])
        open_ = _make_series([100.0, 100.0, 100.0])
        result = _gap_magnitude(open_, close)
        assert result == pytest.approx(0.0)

    def test_gap_up(self):
        close = _make_series([100.0, 100.0, 100.0])
        open_ = _make_series([100.0, 100.0, 105.0])
        result = _gap_magnitude(open_, close)
        assert result is not None
        assert result == pytest.approx(5.0)

    def test_gap_down(self):
        close = _make_series([100.0, 100.0, 100.0])
        open_ = _make_series([100.0, 100.0, 95.0])
        result = _gap_magnitude(open_, close)
        assert result == pytest.approx(5.0)


class TestRangeExpansion:
    def test_normal_range(self):
        high = _make_series([110.0] * 21)
        low = _make_series([90.0] * 21)
        result = _range_expansion(high, low)
        assert result == pytest.approx(1.0)

    def test_expanded_range(self):
        high = _make_series([110.0] * 20 + [130.0])
        low = _make_series([90.0] * 20 + [70.0])
        result = _range_expansion(high, low)
        assert result is not None
        assert result == pytest.approx(3.0)


class TestAnomalyProvider:
    def _make_panel(self, n_days: int = 30, n_syms: int = 5,
                    spike_sym: int = 0) -> dict[str, pd.DataFrame]:
        dates = pd.bdate_range("2025-01-01", periods=n_days)
        syms = [f"SYM{i}.US" for i in range(n_syms)]
        rng = np.random.default_rng(42)

        close = pd.DataFrame(
            100 + rng.normal(0, 1, (n_days, n_syms)).cumsum(axis=0),
            index=dates, columns=syms,
        )
        open_ = close.shift(1).bfill() + rng.normal(0, 0.5, (n_days, n_syms))
        high = close + rng.uniform(0.5, 2, (n_days, n_syms))
        low = close - rng.uniform(0.5, 2, (n_days, n_syms))
        volume = pd.DataFrame(
            rng.uniform(1e6, 2e6, (n_days, n_syms)),
            index=dates, columns=syms,
        )

        if spike_sym is not None:
            volume.iloc[-1, spike_sym] = 1e7

        return {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }

    def test_detects_volume_spike(self):
        panel = self._make_panel(spike_sym=0)
        provider = AnomalyProvider(top_n=10, min_score=5.0)
        asof = str(panel["close"].index[-1].date())
        results = provider.compute(panel, asof)
        assert len(results) > 0
        top = results[0]
        assert top.symbol == "SYM0.US"
        assert "成交量突增" in top.attribution or "成交量突增" in top.detail
        assert top.provider_id == "anomaly"

    def test_respects_min_score(self):
        panel = self._make_panel(spike_sym=None)
        provider = AnomalyProvider(top_n=10, min_score=90.0)
        asof = str(panel["close"].index[-1].date())
        results = provider.compute(panel, asof)
        assert len(results) == 0

    def test_respects_top_n(self):
        panel = self._make_panel(n_syms=50, spike_sym=None)
        provider = AnomalyProvider(top_n=5, min_score=0.0)
        asof = str(panel["close"].index[-1].date())
        results = provider.compute(panel, asof)
        assert len(results) <= 5

    def test_empty_panel(self):
        provider = AnomalyProvider()
        results = provider.compute({"close": pd.DataFrame()}, "2025-06-01")
        assert results == []

    def test_detail_uses_chinese_labels(self):
        panel = self._make_panel(spike_sym=0)
        provider = AnomalyProvider(top_n=10, min_score=5.0)
        asof = str(panel["close"].index[-1].date())
        results = provider.compute(panel, asof)
        assert len(results) > 0
        for key in results[0].detail:
            assert not key.startswith("vol_") and not key.startswith("gap")
