from __future__ import annotations

import pandas as pd

from src.scanner.core import Candidate, run_scan


class _FakeProvider:
    provider_id = "fake"

    def __init__(self):
        self.seen_rows = None

    def compute(self, panel, asof):
        self.seen_rows = len(panel["close"])
        return [Candidate("AAA", 5.0, "fake", "why", {})]


def _panel():
    dates = pd.DatetimeIndex(pd.to_datetime(["2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]))
    return {"close": pd.DataFrame({"AAA": [1, 2, 3, 4], "BBB": [4, 3, 2, 1]}, index=dates)}


def test_run_scan_truncates_panel_to_asof_before_providers():
    prov = _FakeProvider()
    panel = _panel()
    result = run_scan(
        universe="sp500", asof="2026-06-11", providers=[prov],
        panel_loader=lambda universe, period: panel,
    )
    assert prov.seen_rows == 3, "provider must never see rows after asof"
    assert result.candidates[0].symbol == "AAA"
    assert result.providers == ["fake"]
    assert result.universe == "sp500"
    assert result.asof == "2026-06-11"


def test_run_scan_collects_from_multiple_providers():
    class P2:
        provider_id = "p2"
        def compute(self, panel, asof):
            return [Candidate("CCC", 9.0, "p2", "why2", {})]

    result = run_scan(
        universe="sp500", asof="2026-06-11",
        providers=[_FakeProvider(), P2()],
        panel_loader=lambda u, p: _panel(),
    )
    symbols = {c.symbol for c in result.candidates}
    assert symbols == {"AAA", "CCC"}
    assert result.providers == ["fake", "p2"]
