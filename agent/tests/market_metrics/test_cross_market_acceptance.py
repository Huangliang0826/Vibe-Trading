from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.market_metrics.models import MarketBar
from src.market_metrics.service import build_market_metrics_response


FIXTURES = Path(__file__).with_name("fixtures")


@pytest.mark.parametrize("fixture_name", ["us_split", "hk_sparse", "cn_holiday"])
def test_cross_market_metric_contract(fixture_name: str):
    raw = json.loads((FIXTURES / f"{fixture_name}.json").read_text(encoding="utf-8"))
    bars = [MarketBar(timestamp, close, close, close, close, volume) for timestamp, close, volume in raw["bars"]]

    response = build_market_metrics_response(
        symbol=raw["symbol"],
        market=raw["market"],
        currency=raw["currency"],
        period=raw["period"],
        requested_start=date.fromisoformat(raw["requested_start"]),
        bars=bars,
        source="acceptance-fixture",
    )

    assert response.data_status.quality == raw["expected"]["quality"]
    for field in (
        "interval_return_pct",
        "dca_return_pct",
        "buy_hold_max_loss_pct",
        "max_drawdown_pct",
    ):
        assert getattr(response.metrics, field) == pytest.approx(raw["expected"][field])
