from __future__ import annotations

from datetime import date

from src.market_metrics.models import MarketBar
from src.market_metrics.validation import validate_bars


def _bar(timestamp: str, *, volume: float | None = 1_000) -> MarketBar:
    return MarketBar(timestamp, 100.0, 101.0, 99.0, 100.0, volume)


def test_missing_volume_is_warning_not_zero():
    quality = validate_bars([
        _bar("2026-01-02", volume=None),
        _bar("2026-01-05", volume=1_200),
    ])

    assert quality.status == "warning"
    assert [issue.code for issue in quality.issues] == ["missing_volume"]


def test_duplicate_date_and_invalid_ohlc_block_metrics():
    bars = [
        MarketBar("2026-01-02", 100.0, 90.0, 99.0, 100.0, 1_000),
        _bar("2026-01-02"),
    ]

    quality = validate_bars(bars)

    assert quality.status == "invalid"
    assert {issue.code for issue in quality.issues} == {
        "duplicate_timestamp", "invalid_ohlc",
    }


def test_unsorted_non_positive_and_negative_volume_are_invalid():
    quality = validate_bars([
        _bar("2026-01-05"),
        MarketBar("2026-01-02", 0.0, 1.0, 0.0, 0.0, -1.0),
    ])

    assert quality.status == "invalid"
    assert {issue.code for issue in quality.issues} >= {
        "unsorted_timestamp", "non_positive_price", "negative_volume",
    }


def test_stale_data_is_warning():
    quality = validate_bars(
        [_bar("2026-01-02")], expected_latest_date=date(2026, 1, 6),
    )

    assert quality.status == "warning"
    assert any(issue.code == "stale_data" for issue in quality.issues)

