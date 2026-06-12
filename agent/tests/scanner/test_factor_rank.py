from __future__ import annotations

import numpy as np
import pandas as pd

from src.scanner.providers.factor_rank import FactorRankProvider


class _FakeRegistry:
    """Returns a fixed factor frame per id; ignores the panel."""

    def __init__(self, frames):
        self._frames = frames

    def compute(self, alpha_id, panel):
        return self._frames[alpha_id]


def _frame(values: dict[str, list[float]], dates) -> pd.DataFrame:
    return pd.DataFrame(values, index=dates)


def test_higher_factor_value_ranks_higher_for_positive_ir():
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-06-10", "2026-06-11"]))
    # AAA has the highest factor value on the asof row -> should rank #1.
    frames = {"f1": _frame({"AAA": [1.0, 3.0], "BBB": [1.0, 2.0], "CCC": [1.0, 1.0]}, dates)}
    manifest = {"factors": [{"id": "f1", "zoo": "z", "ir": 0.2, "alpha_t": 4.0}]}

    prov = FactorRankProvider(manifest=manifest, registry=_FakeRegistry(frames), top_n=3)
    out = prov.compute({"close": frames["f1"]}, "2026-06-11")

    ranked = sorted(out, key=lambda c: -c.score)
    assert ranked[0].symbol == "AAA"
    assert ranked[-1].symbol == "CCC"
    assert "f1" in ranked[0].detail


def test_negative_ir_factor_inverts_contribution():
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-06-11"]))
    # With negative IR, the LOWEST factor value should rank #1.
    frames = {"f1": _frame({"AAA": [3.0], "BBB": [2.0], "CCC": [1.0]}, dates)}
    manifest = {"factors": [{"id": "f1", "zoo": "z", "ir": -0.2, "alpha_t": 4.0}]}

    prov = FactorRankProvider(manifest=manifest, registry=_FakeRegistry(frames), top_n=3)
    out = prov.compute({"close": frames["f1"]}, "2026-06-11")

    ranked = sorted(out, key=lambda c: -c.score)
    assert ranked[0].symbol == "CCC"


def test_top_n_caps_output():
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-06-11"]))
    frames = {"f1": _frame({c: [float(i)] for i, c in enumerate("ABCDE")}, dates)}
    manifest = {"factors": [{"id": "f1", "zoo": "z", "ir": 0.2, "alpha_t": 4.0}]}

    prov = FactorRankProvider(manifest=manifest, registry=_FakeRegistry(frames), top_n=2)
    out = prov.compute({"close": frames["f1"]}, "2026-06-11")
    assert len(out) == 2


def test_higher_ir_factor_dominates_composite():
    # Two positive-IR factors that disagree: f1 (weight 0.4) favors AAA,
    # f2 (weight 0.1) favors CCC. The higher-|IR| factor must win.
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-06-11"]))
    frames = {
        "f1": _frame({"AAA": [3.0], "BBB": [2.0], "CCC": [1.0]}, dates),
        "f2": _frame({"AAA": [1.0], "BBB": [2.0], "CCC": [3.0]}, dates),
    }
    manifest = {"factors": [
        {"id": "f1", "zoo": "z", "ir": 0.4, "alpha_t": 4.0},
        {"id": "f2", "zoo": "z", "ir": 0.1, "alpha_t": 4.0},
    ]}

    prov = FactorRankProvider(manifest=manifest, registry=_FakeRegistry(frames), top_n=3)
    out = {c.symbol: c for c in prov.compute({"close": frames["f1"]}, "2026-06-11")}

    # Composite (|IR|-weighted, /total_weight, *100): AAA=86.67, BBB=66.67, CCC=46.67
    assert round(out["AAA"].score, 1) == 86.7
    assert round(out["BBB"].score, 1) == 66.7
    assert round(out["CCC"].score, 1) == 46.7
    # AAA's detail carries both factors' contributions.
    assert set(out["AAA"].detail.keys()) == {"f1", "f2"}


def test_nan_union_symbol_in_both_factors_outranks_partial_coverage():
    # f1 covers {AAA, BBB}; f2 covers {AAA, CCC}. fill_value=0.0 union means a
    # symbol present (and strong) in both should outrank ones in only one factor.
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-06-11"]))
    frames = {
        "f1": _frame({"AAA": [2.0], "BBB": [1.0]}, dates),
        "f2": _frame({"AAA": [1.0], "CCC": [2.0]}, dates),
    }
    manifest = {"factors": [
        {"id": "f1", "zoo": "z", "ir": 0.3, "alpha_t": 4.0},
        {"id": "f2", "zoo": "z", "ir": 0.3, "alpha_t": 4.0},
    ]}

    prov = FactorRankProvider(manifest=manifest, registry=_FakeRegistry(frames), top_n=3)
    ranked = sorted(prov.compute({"close": frames["f1"]}, "2026-06-11"),
                    key=lambda c: -c.score)

    # Composite*100: AAA=75.0 (top of f1, mid of f2), CCC=50.0 (top of f2 only),
    # BBB=25.0 (bottom of f1 only).
    assert [c.symbol for c in ranked] == ["AAA", "CCC", "BBB"]
    assert round(ranked[0].score, 1) == 75.0
    assert round(ranked[-1].score, 1) == 25.0
