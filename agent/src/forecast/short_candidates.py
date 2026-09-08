"""Rank watchlist symbols by how bearish the forecast is ("worth shorting").

Source of the view: the TimesFM cone's median path (``p50``) versus the last
close, corroborated by whether the robust strategy is currently FLAT — i.e. the
long-only strategy does not want to hold it either.

Two honesty constraints are baked in rather than left to the UI:

* The cone's 80% band is usually far wider than the median drift (AAPL: a +1.5%
  median inside a ±16% band). ``signal_to_band`` exposes that ratio so a
  confident-looking ranking cannot hide how weak the underlying edge is.
* The forecast's direction accuracy is not statistically established (see the
  edge scorecard), so these are *candidates to examine*, never recommendations.

Nothing here trades: the paper executor is long-only and ignores this module.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable, Iterable, Optional


@dataclass(frozen=True)
class ShortCandidate:
    market: str
    code: str
    name: str
    last_close: float
    expected_return_pct: float   # p50 endpoint vs last close
    downside_return_pct: float   # p10 endpoint vs last close
    upside_return_pct: float     # p90 endpoint vs last close
    band_width_pct: float        # p90 - p10, in points of return
    signal_to_band: float        # |expected| / band width; higher == less noise
    strategy_flat: bool          # robust strategy is not currently long
    strategy_label: str
    horizon_days: int

    def to_dict(self) -> dict:
        return asdict(self)


def _pct(value: float, base: float) -> float:
    return (value / base - 1.0) * 100.0


def score_symbol(
    market: str,
    code: str,
    forecast: dict,
    *,
    strategy_flat: bool = False,
    strategy_label: str = "",
) -> Optional[ShortCandidate]:
    """Turn one forecast payload into a candidate, or None when unusable."""
    model = (forecast or {}).get("model")
    history = (forecast or {}).get("history") or []
    if not model or not history:
        return None
    try:
        last_close = float(history[-1]["close"])
        p50 = [float(v) for v in model["p50"]]
        p10 = [float(v) for v in model["p10"]]
        p90 = [float(v) for v in model["p90"]]
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if last_close <= 0 or not p50 or not p10 or not p90:
        return None

    expected = _pct(p50[-1], last_close)
    downside = _pct(p10[-1], last_close)
    upside = _pct(p90[-1], last_close)
    band = upside - downside
    return ShortCandidate(
        market=market,
        code=code,
        name=str((forecast or {}).get("name") or code),
        last_close=round(last_close, 4),
        expected_return_pct=round(expected, 2),
        downside_return_pct=round(downside, 2),
        upside_return_pct=round(upside, 2),
        band_width_pct=round(band, 2),
        signal_to_band=round(abs(expected) / band, 4) if band > 0 else 0.0,
        strategy_flat=bool(strategy_flat),
        strategy_label=strategy_label or "",
        horizon_days=int((forecast or {}).get("horizon") or len(p50)),
    )


def rank_short_candidates(
    candidates: Iterable[ShortCandidate], *, limit: int = 5,
) -> list[ShortCandidate]:
    """Most bearish first. Only genuine declines qualify.

    Ties break toward the cleaner signal (higher signal-to-band), so a symbol
    whose decline is merely wide noise ranks below an equally negative one with
    a tighter cone.
    """
    bearish = [c for c in candidates if c.expected_return_pct < 0]
    bearish.sort(key=lambda c: (c.expected_return_pct, -c.signal_to_band))
    return bearish[: max(0, limit)]


def build_short_candidates(
    symbols: Iterable[tuple[str, str]],
    fetch_forecast: Callable[[str, str], dict],
    fetch_strategy: Callable[[str, str], tuple[bool, str]],
    *,
    limit: int = 5,
) -> tuple[list[ShortCandidate], list[dict[str, Any]]]:
    """Score every symbol, returning (ranked candidates, skipped reasons)."""
    scored: list[ShortCandidate] = []
    skipped: list[dict[str, Any]] = []
    for market, code in symbols:
        try:
            forecast = fetch_forecast(market, code)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not sink the list
            skipped.append({"code": code, "reason": f"forecast_error:{exc}"})
            continue
        try:
            flat, label = fetch_strategy(market, code)
        except Exception:  # noqa: BLE001 - corroboration is optional
            flat, label = False, ""
        candidate = score_symbol(market, code, forecast, strategy_flat=flat, strategy_label=label)
        if candidate is None:
            skipped.append({"code": code, "reason": "no_model"})
            continue
        scored.append(candidate)
    return rank_short_candidates(scored, limit=limit), skipped
