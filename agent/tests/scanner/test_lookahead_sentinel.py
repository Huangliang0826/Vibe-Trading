from __future__ import annotations

import numpy as np
import pandas as pd

from src.scanner.core import run_scan
from src.scanner.providers.factor_rank import FactorRankProvider


class _PassthroughRegistry:
    """compute(id, panel) returns panel['close'] so factor == price."""
    def compute(self, alpha_id, panel):
        return panel["close"]


def _panel(future_value: float):
    dates = pd.DatetimeIndex(pd.to_datetime(
        ["2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]))
    return {"close": pd.DataFrame(
        {"AAA": [1.0, 2.0, 3.0, future_value],
         "BBB": [3.0, 2.0, 1.0, future_value],
         "CCC": [2.0, 2.0, 2.0, future_value]},
        index=dates,
    )}


def test_corrupting_future_rows_does_not_change_candidates():
    manifest = {"factors": [{"id": "f1", "zoo": "z", "ir": 0.2, "alpha_t": 4.0}]}

    def make_provider():
        return FactorRankProvider(manifest=manifest, registry=_PassthroughRegistry(), top_n=3)

    clean = run_scan("sp500", "2026-06-11", [make_provider()],
                     panel_loader=lambda u, p: _panel(4.0)).to_dict()
    poisoned = run_scan("sp500", "2026-06-11", [make_provider()],
                        panel_loader=lambda u, p: _panel(9999.0)).to_dict()

    assert clean["candidates"] == poisoned["candidates"], (
        "future-row corruption changed the leaderboard -> look-ahead leak"
    )
