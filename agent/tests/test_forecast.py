"""Unit tests for the forecast package (baselines, service assembly, backtest).

These deliberately avoid loading TimesFM: the model path is exercised by mocking
``engine.forecast`` / ``engine.is_available`` so the suite stays fast and offline.
"""
from __future__ import annotations

import math

import pytest

from src.forecast import baselines, service, backtest, engine


# ── context resolution ───────────────────────────────────────────────────────

def test_resolve_context_all_when_unset():
    # None / 0 → use everything available (under the ceiling)
    assert engine.resolve_context(800, None) == 800
    assert engine.resolve_context(800, 0) == 800


def test_resolve_context_clamps():
    assert engine.resolve_context(800, 300) == 300          # honor request
    assert engine.resolve_context(800, 5000) == 800         # capped to available
    assert engine.resolve_context(10000, 5000) == 3650      # capped to ceiling
    assert engine.resolve_context(800, 10) == 32            # floor at 32


def _bars(n: int, start: float = 100.0, step: float = 0.5) -> list[dict]:
    return [
        {"date": f"2026-01-{(i % 28) + 1:02d}", "close": start + step * i, "volume": 1000}
        for i in range(n)
    ]


# ── baselines ────────────────────────────────────────────────────────────────

def test_random_walk_is_flat():
    out = baselines.random_walk([10, 11, 12], 5)
    assert out == [12.0] * 5


def test_drift_extrapolates_trend():
    out = baselines.drift([100, 101, 102, 103], 3, lookback=4)
    # avg step = 1 → 104, 105, 106
    assert out == pytest.approx([104.0, 105.0, 106.0])


def test_drift_short_series():
    assert baselines.drift([5.0], 3) == [5.0, 5.0, 5.0]


# ── service ──────────────────────────────────────────────────────────────────

def test_build_forecast_without_model(monkeypatch):
    monkeypatch.setattr(service.engine, "is_available", lambda: False)
    out = service.build_forecast(_bars(120), horizon=10, with_model=False)
    assert out["model"] is None
    assert len(out["future_dates"]) == 10
    assert len(out["baselines"]["random_walk"]) == 10
    # future dates are weekdays only
    import datetime as dt
    for d in out["future_dates"]:
        assert dt.date.fromisoformat(d).weekday() < 5


def test_build_forecast_uses_model_when_available(monkeypatch):
    def fake_forecast(closes, horizon, context=None):
        return {"point": [1.0] * horizon, "p10": [0.0] * horizon,
                "p50": [1.0] * horizon, "p90": [2.0] * horizon,
                "context_used": len(closes)}
    monkeypatch.setattr(service.engine, "forecast", fake_forecast)
    monkeypatch.setattr(service.engine, "is_available", lambda: True)
    out = service.build_forecast(_bars(120), horizon=7)
    assert out["model"]["p90"] == [2.0] * 7
    assert "context_used" not in out["model"]  # popped up to top level
    assert out["context_used"] == 120


def test_build_forecast_passes_context(monkeypatch):
    seen = {}
    def fake_forecast(closes, horizon, context=None):
        seen["context"] = context
        return {"point": [1.0] * horizon, "p10": [0.0] * horizon,
                "p50": [1.0] * horizon, "p90": [2.0] * horizon, "context_used": 50}
    monkeypatch.setattr(service.engine, "forecast", fake_forecast)
    monkeypatch.setattr(service.engine, "is_available", lambda: True)
    service.build_forecast(_bars(120), horizon=5, context=50)
    assert seen["context"] == 50


def test_build_forecast_filters_nan_close():
    bars = _bars(40)
    bars[-1]["close"] = float("nan")  # trailing incomplete session
    out = service.build_forecast(bars, horizon=5, with_model=False)
    rw = out["baselines"]["random_walk"][0]
    assert math.isfinite(rw)


def test_build_forecast_insufficient_history():
    out = service.build_forecast(_bars(10), horizon=5, with_model=False)
    assert out["error"] == "insufficient_history"


# ── interval score (sharpness + calibration) ─────────────────────────────────

def test_interval_score_rewards_tight_covered():
    # y inside both, narrower interval scores lower (better)
    tight = backtest._interval_score(95, 105, 100)
    wide = backtest._interval_score(80, 120, 100)
    assert tight < wide  # narrower wins when both cover


def test_interval_score_punishes_miss():
    # same width, but one misses → miss is penalized heavily (2/alpha)
    covered = backtest._interval_score(95, 105, 100)
    missed = backtest._interval_score(95, 105, 130)  # y above upper by 25
    assert missed > covered
    # penalty term = (2/0.2)*(130-105) = 250, plus width 10
    assert missed == pytest.approx(10 + 10 * 25)


def test_interval_score_cannot_be_gamed_by_widening():
    # widening to guarantee coverage still costs via the width term
    y = 100
    narrow_miss = backtest._interval_score(101, 109, y)   # misses low
    huge_cover = backtest._interval_score(0, 100000, y)   # covers but absurd
    assert huge_cover > narrow_miss  # absurd width is not "free"


# ── conformal prediction (CQR) ───────────────────────────────────────────────

class TestConformalSplit:
    def test_too_few_folds(self):
        assert backtest._conformal([1] * 10, [2] * 10, [1.5] * 10) is None

    def test_undercovering_band_widens_to_target(self):
        import numpy as np
        rng = np.random.default_rng(0)
        n = 200
        # True values ~ N(0,1); model claims a far-too-narrow [-0.2, 0.2] band
        ys = rng.normal(0, 1, n)
        lo = [-0.2] * n
        hi = [0.2] * n
        out = backtest._conformal(lo, hi, ys, alpha=0.2)
        assert out is not None
        assert out["q"] > 0                       # had to widen
        assert out["coverage_raw"] < 0.5          # raw badly under-covers
        assert out["coverage_conformal"] >= 0.70  # conformal ≈ 80% target
        assert out["width_conformal"] > out["width_raw"]

    def test_overwide_band_tightens(self):
        import numpy as np
        ys = list(np.zeros(100))                  # all reality at 0
        lo = [-100.0] * 100                       # absurdly wide band
        hi = [100.0] * 100
        out = backtest._conformal(lo, hi, ys, alpha=0.2)
        assert out["q"] < 0                        # can safely tighten
        assert out["width_conformal"] < out["width_raw"]


# ── backtest ─────────────────────────────────────────────────────────────────

def test_calibration_insufficient_history(monkeypatch):
    monkeypatch.setattr(backtest.engine, "is_available", lambda: False)
    out = backtest.calibration(_bars(20), bt_horizon=63)
    assert out["n_folds"] == 0
    assert out["error"] == "insufficient_history"


def test_calibration_runs_with_mocked_model(monkeypatch):
    monkeypatch.setattr(backtest.engine, "is_available", lambda: True)

    def fake_forecast(closes, horizon, context=None):
        last = closes[-1]
        return {"point": [last] * horizon, "p10": [last - 5] * horizon,
                "p50": [last] * horizon, "p90": [last + 5] * horizon,
                "context_used": len(closes)}
    monkeypatch.setattr(backtest.engine, "forecast", fake_forecast)

    out = backtest.calibration(_bars(300, step=0.5), bt_horizon=21, step=20, max_folds=10)
    assert out["n_folds"] > 0
    assert out["context_used"] > 0
    assert out["mae"]["model"] is not None
    assert out["mae"]["random_walk"] is not None
    # coverage is a fraction in [0, 1]
    assert 0.0 <= out["interval_coverage_80"] <= 1.0
