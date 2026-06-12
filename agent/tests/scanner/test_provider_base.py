from __future__ import annotations

import pandas as pd

from src.scanner.core import Candidate
from src.scanner.providers.base import SignalProvider


def test_provider_is_abstract_and_subclass_computes():
    class FakeProvider(SignalProvider):
        provider_id = "fake"

        def compute(self, panel, asof):
            return [Candidate("AAA", 1.0, self.provider_id, "test", {})]

    p = FakeProvider()
    out = p.compute({"close": pd.DataFrame()}, "2026-06-11")
    assert out[0].symbol == "AAA"
    assert out[0].provider_id == "fake"
