"""anomaly: detect volume spikes, volatility shifts, and price gaps."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.scanner.core import Candidate
from src.scanner.providers.base import SignalProvider

_LOOKBACK = 20


def _safe_tail(series: pd.Series, n: int) -> pd.Series:
    """Last *n* non-NaN values (or fewer if not enough data)."""
    valid = series.dropna()
    return valid.iloc[-n:] if len(valid) >= n else valid


def _volume_spike(volume: pd.Series) -> float | None:
    """Ratio of latest volume to 20-day mean; >2 is notable."""
    tail = _safe_tail(volume, _LOOKBACK + 1)
    if len(tail) < _LOOKBACK + 1:
        return None
    avg = tail.iloc[:-1].mean()
    if avg <= 0:
        return None
    return float(tail.iloc[-1] / avg)


def _volume_trend(volume: pd.Series) -> float | None:
    """5-day avg / 20-day avg — rising volume trend."""
    tail = _safe_tail(volume, _LOOKBACK)
    if len(tail) < _LOOKBACK:
        return None
    avg20 = tail.mean()
    avg5 = tail.iloc[-5:].mean()
    if avg20 <= 0:
        return None
    return float(avg5 / avg20)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = _LOOKBACK) -> pd.Series:
    """Average True Range over last *n* bars."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def _volatility_contraction(high: pd.Series, low: pd.Series, close: pd.Series) -> float | None:
    """ATR(5) / ATR(20) — values < 0.7 signal contraction (potential breakout)."""
    if len(close.dropna()) < _LOOKBACK + 5:
        return None
    atr20 = _atr(high, low, close, _LOOKBACK)
    atr5 = _atr(high, low, close, 5)
    latest_20 = atr20.dropna()
    latest_5 = atr5.dropna()
    if latest_20.empty or latest_5.empty:
        return None
    val20 = float(latest_20.iloc[-1])
    if val20 <= 0:
        return None
    return float(latest_5.iloc[-1] / val20)


def _gap_magnitude(open_: pd.Series, close: pd.Series) -> float | None:
    """Absolute gap % = |open_today / close_yesterday - 1|."""
    c = close.dropna()
    o = open_.dropna()
    if len(c) < 2 or len(o) < 1:
        return None
    prev_close = float(c.iloc[-2])
    if prev_close <= 0:
        return None
    return float(abs(o.iloc[-1] / prev_close - 1) * 100)


def _range_expansion(high: pd.Series, low: pd.Series) -> float | None:
    """Today's range / 20-day avg range."""
    daily_range = high - low
    tail = _safe_tail(daily_range, _LOOKBACK + 1)
    if len(tail) < _LOOKBACK + 1:
        return None
    avg = tail.iloc[:-1].mean()
    if avg <= 0:
        return None
    return float(tail.iloc[-1] / avg)


SIGNAL_LABELS: dict[str, str] = {
    "vol_spike": "成交量突增",
    "vol_trend": "量能趋势",
    "vol_contraction": "波动率收缩",
    "gap": "跳空缺口",
    "range_expansion": "振幅放大",
}

_WEIGHTS: dict[str, float] = {
    "vol_spike": 30.0,
    "vol_trend": 15.0,
    "vol_contraction": 20.0,
    "gap": 15.0,
    "range_expansion": 20.0,
}


def _score_signal(name: str, value: float) -> float:
    """Convert a raw signal value to a 0-100 contribution score."""
    if name == "vol_spike":
        return min(float(np.clip((value - 1.0) / 3.0, 0, 1)) * 100, 100)
    if name == "vol_trend":
        return min(float(np.clip((value - 0.8) / 1.2, 0, 1)) * 100, 100)
    if name == "vol_contraction":
        score = float(np.clip((1.0 - value) / 0.5, 0, 1)) * 100
        return min(score, 100)
    if name == "gap":
        return min(float(np.clip(value / 5.0, 0, 1)) * 100, 100)
    if name == "range_expansion":
        return min(float(np.clip((value - 1.0) / 3.0, 0, 1)) * 100, 100)
    return 0.0


class AnomalyProvider(SignalProvider):
    """Detect technical anomalies: volume spikes, volatility shifts, gaps."""

    provider_id = "anomaly"

    def __init__(self, top_n: int = 20, min_score: float = 15.0):
        self._top_n = top_n
        self._min_score = min_score

    def compute(self, panel: dict[str, pd.DataFrame], asof: str) -> list[Candidate]:
        close = panel.get("close")
        volume = panel.get("volume")
        high = panel.get("high")
        low = panel.get("low")
        open_ = panel.get("open")

        if close is None or close.empty:
            return []

        symbols = [c for c in close.columns if not str(c).startswith("_")]
        results: list[Candidate] = []

        for sym in symbols:
            signals: dict[str, float] = {}

            if volume is not None and sym in volume.columns:
                v = _volume_spike(volume[sym])
                if v is not None:
                    signals["vol_spike"] = v
                vt = _volume_trend(volume[sym])
                if vt is not None:
                    signals["vol_trend"] = vt

            if high is not None and low is not None and sym in high.columns:
                vc = _volatility_contraction(high[sym], low[sym], close[sym])
                if vc is not None:
                    signals["vol_contraction"] = vc
                re = _range_expansion(high[sym], low[sym])
                if re is not None:
                    signals["range_expansion"] = re

            if open_ is not None and sym in open_.columns:
                g = _gap_magnitude(open_[sym], close[sym])
                if g is not None:
                    signals["gap"] = g

            if not signals:
                continue

            weighted_sum = 0.0
            total_weight = 0.0
            detail: dict[str, float] = {}
            for name, raw in signals.items():
                w = _WEIGHTS.get(name, 10.0)
                scored = _score_signal(name, raw)
                weighted_sum += scored * w
                total_weight += w
                label = SIGNAL_LABELS.get(name, name)
                detail[label] = round(scored, 1)

            if total_weight == 0:
                continue

            composite = weighted_sum / total_weight
            if composite < self._min_score:
                continue

            detail = dict(sorted(detail.items(), key=lambda kv: -kv[1]))
            top_names = [k for k, v in list(detail.items())[:2] if v > 0]
            attribution = (
                "、".join(top_names) + " 异常" if top_names else "技术面异常"
            )

            results.append(Candidate(
                symbol=str(sym),
                score=round(composite, 2),
                provider_id=self.provider_id,
                attribution=attribution,
                detail=detail,
            ))

        results.sort(key=lambda c: -c.score)
        return results[:self._top_n]
