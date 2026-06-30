from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from src.opportunity_center.market_context import (
    _compute_market_context,
    _valuation_percentile,
    load_market_context,
)


def make_market_frame(start: str, periods: int) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="B")
    close = pd.Series(np.linspace(100.0, 220.0, periods), index=index, dtype=float)
    volume = pd.Series(np.linspace(1_000_000.0, 2_000_000.0, periods), index=index, dtype=float)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
        },
        index=index,
    )
    frame.index.name = "trade_date"
    return frame


def test_compute_market_context_uses_exact_trend_and_risk_formulas():
    frame = make_market_frame("2024-01-01", periods=260)
    as_of = frame.index[-1].date()

    context = _compute_market_context(frame, market="hk", code="0700", as_of=as_of, valuation_percentile=75.0)

    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    returns = close.pct_change().dropna()
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    momentum63 = close.iloc[-1] / close.iloc[-64] - 1
    annual_vol = returns.tail(63).std() * math.sqrt(252)
    downside_vol = returns.tail(63).clip(upper=0).std() * math.sqrt(252)
    max_drawdown = (close / close.cummax() - 1).min()
    return20 = close.iloc[-1] / close.iloc[-21] - 1
    volume_ratio = volume.tail(20).mean() / volume.tail(60).mean()
    volume_confirmation = 10 if momentum63 > 0 and volume_ratio >= 1.2 else 0
    expected_trend = max(
        0.0,
        min(
            100.0,
            50.0
            + 15.0
            + 10.0
            + max(-15.0, min(momentum63 * 100.0, 15.0))
            + volume_confirmation,
        ),
    )
    expected_risk = max(
        0.0,
        min(
            100.0,
            100.0
            - min(annual_vol, 1.0) * 45.0
            - min(abs(max_drawdown), 1.0) * 40.0
            - min(downside_vol, 1.0) * 15.0,
        ),
    )

    assert context.latest_price_date == as_of.isoformat()
    assert context.trend_inputs == {
        "close": pytest.approx(close.iloc[-1]),
        "sma50": pytest.approx(sma50),
        "sma200": pytest.approx(sma200),
        "momentum63": pytest.approx(momentum63),
        "volume_ratio": pytest.approx(volume_ratio),
    }
    assert context.risk_inputs == {
        "annual_vol": pytest.approx(annual_vol),
        "downside_vol": pytest.approx(downside_vol),
        "max_drawdown": pytest.approx(max_drawdown),
        "return20": pytest.approx(return20),
    }
    assert context.trend_score == pytest.approx(expected_trend)
    assert context.risk_score == pytest.approx(expected_risk)
    assert context.valuation_percentile == pytest.approx(75.0)


def test_load_market_context_ignores_rows_after_as_of(monkeypatch: pytest.MonkeyPatch):
    base = make_market_frame("2024-01-01", periods=260)
    mutated = base.copy()
    future_index = pd.date_range(base.index[-1] + pd.offsets.BDay(1), periods=10, freq="B")
    future = pd.DataFrame(
        {
            "open": 9_999.0,
            "high": 10_100.0,
            "low": 9_500.0,
            "close": 10_000.0,
            "volume": 90_000_000.0,
        },
        index=future_index,
    )
    mutated = pd.concat([mutated, future])

    monkeypatch.setattr("src.opportunity_center.market_context._load_price_history", lambda *args, **kwargs: mutated)
    monkeypatch.setattr("src.opportunity_center.market_context._fetch_hk_valuation_history", lambda *args, **kwargs: None)

    trimmed = _compute_market_context(base, market="hk", code="0700", as_of=base.index[-1].date(), valuation_percentile=None)
    loaded = load_market_context("hk", "0700", as_of=base.index[-1].date())

    assert loaded.model_dump() == trimmed.model_dump()


def test_valuation_percentile_prefers_pe_with_at_least_30_positive_values():
    pe_history = pd.DataFrame(
        {
            "pe": list(range(1, 31)),
            "pb": list(range(30, 0, -1)),
        }
    )
    assert _valuation_percentile(pe_history) == pytest.approx(100.0)


def test_valuation_percentile_falls_back_to_pb_with_at_least_30_positive_values():
    pe_values = [None] * 28 + [-1.0, 0.0, 8.0, None]
    pb_history = pd.DataFrame(
        {
            "pe": pe_values,
            "pb": list(range(1, 33)),
        }
    )
    assert _valuation_percentile(pb_history) == pytest.approx(100.0)


def test_valuation_percentile_returns_none_with_fewer_than_30_positive_pb_values():
    history = pd.DataFrame(
        {
            "pe": [float("nan")] * 29,
            "pb": list(range(1, 29)) + [float("inf")],
        }
    )

    assert _valuation_percentile(history) is None


def test_load_market_context_leaves_us_valuation_empty(monkeypatch: pytest.MonkeyPatch):
    frame = make_market_frame("2024-01-01", periods=260)
    monkeypatch.setattr("src.opportunity_center.market_context._load_price_history", lambda *args, **kwargs: frame)

    context = load_market_context("us", "AAPL", as_of=frame.index[-1].date())

    assert context.valuation_percentile is None
