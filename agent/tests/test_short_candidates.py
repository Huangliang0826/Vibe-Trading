"""Bearish-forecast ranking for the 最值得做空 panel."""
from __future__ import annotations

from src.forecast.short_candidates import (
    ShortCandidate, build_short_candidates, rank_short_candidates, score_symbol,
)


def _fc(last, p50_end, p10_end, p90_end, name="X", horizon=63):
    return {
        "name": name,
        "horizon": horizon,
        "history": [{"date": "2026-08-24", "close": last}],
        "model": {"p50": [last, p50_end], "p10": [last, p10_end], "p90": [last, p90_end]},
    }


def test_score_symbol_computes_returns_and_band():
    c = score_symbol("us", "XYZ", _fc(100.0, 90.0, 70.0, 115.0), strategy_flat=True, strategy_label="ATR")
    assert c is not None
    assert c.expected_return_pct == -10.0
    assert c.downside_return_pct == -30.0
    assert c.upside_return_pct == 15.0
    assert c.band_width_pct == 45.0
    assert c.signal_to_band == round(10.0 / 45.0, 4)
    assert c.strategy_flat is True and c.strategy_label == "ATR"
    assert c.horizon_days == 63


def test_score_symbol_rejects_payload_without_model():
    assert score_symbol("us", "X", {"history": [{"close": 10}], "model": None}) is None
    assert score_symbol("us", "X", {"history": [], "model": {"p50": [1], "p10": [1], "p90": [1]}}) is None
    assert score_symbol("us", "X", {}) is None


def test_score_symbol_rejects_nonpositive_close():
    assert score_symbol("us", "X", _fc(0.0, 1.0, 1.0, 1.0)) is None


def _cand(code, exp, s2b=0.5):
    return ShortCandidate(
        market="us", code=code, name=code, last_close=100.0,
        expected_return_pct=exp, downside_return_pct=exp - 20, upside_return_pct=exp + 20,
        band_width_pct=40.0, signal_to_band=s2b, strategy_flat=True,
        strategy_label="", horizon_days=63,
    )


def test_rank_keeps_only_declines_most_bearish_first():
    ranked = rank_short_candidates(
        [_cand("UP", 5.0), _cand("MILD", -2.0), _cand("DEEP", -12.0)], limit=5,
    )
    assert [c.code for c in ranked] == ["DEEP", "MILD"]   # the riser is excluded


def test_rank_breaks_ties_toward_the_cleaner_signal():
    noisy = _cand("NOISY", -8.0, s2b=0.1)
    clean = _cand("CLEAN", -8.0, s2b=0.9)
    assert [c.code for c in rank_short_candidates([noisy, clean], limit=5)] == ["CLEAN", "NOISY"]


def test_rank_respects_limit():
    cands = [_cand(f"S{i}", -float(i + 1)) for i in range(10)]
    assert len(rank_short_candidates(cands, limit=3)) == 3


def test_build_skips_bad_symbols_without_sinking_the_list():
    def fetch_forecast(market, code):
        if code == "BOOM":
            raise RuntimeError("data source down")
        if code == "NOMODEL":
            return {"history": [{"close": 10}], "model": None}
        return _fc(100.0, 85.0, 60.0, 110.0, name=code)

    def fetch_strategy(market, code):
        return True, "ATR 趋势止损"

    ranked, skipped = build_short_candidates(
        [("us", "BOOM"), ("us", "NOMODEL"), ("us", "GOOD")],
        fetch_forecast, fetch_strategy, limit=5,
    )
    assert [c.code for c in ranked] == ["GOOD"]
    assert {s["code"] for s in skipped} == {"BOOM", "NOMODEL"}


def test_build_tolerates_strategy_lookup_failure():
    def fetch_strategy(market, code):
        raise RuntimeError("strategy unavailable")

    ranked, _ = build_short_candidates(
        [("us", "GOOD")], lambda m, c: _fc(100.0, 85.0, 60.0, 110.0), fetch_strategy,
    )
    # Corroboration is optional — the candidate still ranks, just uncorroborated.
    assert ranked[0].strategy_flat is False and ranked[0].strategy_label == ""
