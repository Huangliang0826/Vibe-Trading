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
