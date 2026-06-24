"""Tests for the forecast-driven strategy backtest (mocked engine, offline)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.forecast import strategy


def _bars(closes: list[float]):
    dates = pd.bdate_range("2018-01-01", periods=len(closes))
    return [{"date": d.strftime("%Y-%m-%d"), "close": c}
            for d, c in zip(dates, closes)]


# ── signal logic ─────────────────────────────────────────────────────────────

class TestBandSignal:
    def test_buy_below_p10(self):
        assert strategy._sig_band(90, p10=95, p50=100, cur=0) == 1

    def test_no_buy_inside_band(self):
        assert strategy._sig_band(98, p10=95, p50=100, cur=0) == 0

    def test_exit_at_p50(self):
        assert strategy._sig_band(101, p10=95, p50=100, cur=1) == 0

    def test_hold_below_p50(self):
        assert strategy._sig_band(98, p10=95, p50=100, cur=1) == 1


class TestTrendSignal:
    def test_buy_when_median_above(self):
        assert strategy._sig_trend(100, p50=110, cur=0) == 1

    def test_no_buy_when_median_below(self):
        assert strategy._sig_trend(100, p50=100, cur=0) == 0

    def test_exit_when_median_drops_below(self):
        assert strategy._sig_trend(100, p50=99, cur=1) == 0


# ── full backtest with mocked forecasts ──────────────────────────────────────

def _mock_forecast_factory(p10_off, p50_off):
    """Return a forecast fn whose quantiles are fixed offsets from last price."""
    def fake(closes, horizon, context=None):
        last = closes[-1]
        return {
            "point": [last] * horizon,
            "p10": [last * (1 + p10_off)] * horizon,
            "p50": [last * (1 + p50_off)] * horizon,
            "p90": [last * 1.1] * horizon,
            "context_used": len(closes),
        }
    return fake


def test_backtest_shapes_and_benchmark(monkeypatch):
    monkeypatch.setattr(strategy.engine, "is_available", lambda: True)
    # median always 2% above price → trend strategy stays long the whole window
    monkeypatch.setattr(strategy.engine, "forecast", _mock_forecast_factory(-0.05, 0.02))

    closes = list(np.linspace(100, 200, 400))  # steady uptrend
    out = strategy.backtest_strategy(_bars(closes), rebalance=5, cost_bps=5,
                                     eval_days=120, lead=21)

    assert out["model_available"] is True
    for key in ("band_reversion", "median_trend"):
        s = out["strategies"][key]
        assert "metrics" in s and "equity" in s
        assert len(s["equity"]) > 0
        assert s["equity"][0][0] < s["equity"][-1][0]  # dates ascending
    bh = out["buy_and_hold"]["metrics"]
    # buy-and-hold over an uptrending eval window must be positive
    assert bh["total_return"] > 0.1
    dca = out["dca"]
    assert "metrics" in dca and "equity" in dca
    assert len(dca["equity"]) == len(out["buy_and_hold"]["equity"])
    assert dca["metrics"]["total_return"] > 0
    assert "beats_buy_and_hold" in out


def test_trend_long_whole_window_matches_buyhold_gross(monkeypatch):
    # median forecast always above price → trend holds continuously; with zero
    # cost its return should ≈ buy-and-hold (only the first-bar entry differs).
    monkeypatch.setattr(strategy.engine, "is_available", lambda: True)
    monkeypatch.setattr(strategy.engine, "forecast", _mock_forecast_factory(-0.05, 0.05))

    closes = list(np.linspace(100, 150, 400))
    out = strategy.backtest_strategy(_bars(closes), rebalance=5, cost_bps=0.0,
                                     eval_days=120, lead=21)
    trend = out["strategies"]["median_trend"]["metrics"]["total_return"]
    bh = out["buy_and_hold"]["metrics"]["total_return"]
    assert trend == pytest.approx(bh, abs=0.02)


def test_cost_reduces_return(monkeypatch):
    monkeypatch.setattr(strategy.engine, "is_available", lambda: True)
    # oscillating signal → frequent turnover so costs bite
    monkeypatch.setattr(strategy.engine, "forecast", _mock_forecast_factory(-0.01, 0.0))

    closes = list(100 + 10 * np.sin(np.linspace(0, 20, 500)))
    free = strategy.backtest_strategy(_bars(closes), rebalance=5, cost_bps=0.0, eval_days=200)
    paid = strategy.backtest_strategy(_bars(closes), rebalance=5, cost_bps=50.0, eval_days=200)
    f = free["strategies"]["band_reversion"]["metrics"]["total_return"]
    p = paid["strategies"]["band_reversion"]["metrics"]["total_return"]
    assert p <= f


def test_insufficient_history():
    out = strategy.backtest_strategy(_bars([100.0] * 50))
    assert out["error"] == "insufficient_history"


def test_vol_target_present_and_fractional(monkeypatch):
    monkeypatch.setattr(strategy.engine, "is_available", lambda: True)
    monkeypatch.setattr(strategy.engine, "forecast", _mock_forecast_factory(-0.05, 0.0))
    closes = list(100 + 5 * np.sin(np.linspace(0, 15, 500)))
    out = strategy.backtest_strategy(_bars(closes), rebalance=5, cost_bps=5, eval_days=200)
    vol = out["strategies"]["vol_target"]
    assert "metrics" in vol and len(vol["equity"]) > 0
    assert "vol_target_calmar_better" in out


# ── robustness aggregation ───────────────────────────────────────────────────

def _fake_result(code, bh_ret, band_excess, vol_dd, bh_dd):
    return {
        "code": code, "name": code,
        "strategies": {
            "band_reversion": {"metrics": {"total_return": bh_ret + band_excess,
                                           "max_drawdown": -0.2, "calmar": 0.5}},
            "median_trend": {"metrics": {"total_return": bh_ret - 0.1,
                                         "max_drawdown": -0.3, "calmar": -0.2}},
            "vol_target": {"metrics": {"total_return": bh_ret - 0.02,
                                       "max_drawdown": vol_dd, "calmar": 0.8}},
        },
        "buy_and_hold": {"metrics": {"total_return": bh_ret, "max_drawdown": bh_dd}},
    }


def test_summarize_robustness():
    items = [
        _fake_result("A", 0.50, +0.05, vol_dd=-0.15, bh_dd=-0.30),  # band beats
        _fake_result("B", 0.40, -0.10, vol_dd=-0.25, bh_dd=-0.20),  # band loses
    ]
    s = strategy.summarize_robustness(items)
    assert s["n"] == 2
    # band excess = [+0.05, -0.10] → 50% positive, median -0.025
    assert s["excess"]["band_reversion"]["pct_positive"] == pytest.approx(0.5)
    assert s["excess"]["band_reversion"]["median"] == pytest.approx(-0.025)
    # vol_target shallower drawdown than B&H: A yes (-0.15>-0.30), B no (-0.25<-0.20)
    assert s["vol_target_dd_better_pct"] == pytest.approx(0.5)


def test_summarize_robustness_skips_errored():
    items = [_fake_result("A", 0.5, 0.05, -0.15, -0.30), {"code": "B", "error": "x"}]
    s = strategy.summarize_robustness(items)
    assert s["n"] == 1
