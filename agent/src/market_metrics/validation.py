"""Deterministic validation for canonical OHLCV bars."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Sequence

from .models import DataQuality, MarketBar, QualityIssue


def _bar_date(timestamp: str) -> date | None:
    try:
        return datetime.fromisoformat(timestamp[:10]).date()
    except (TypeError, ValueError):
        return None


def validate_bars(
    bars: Sequence[MarketBar], *, expected_latest_date: date | None = None,
) -> DataQuality:
    issues: list[QualityIssue] = []
    timestamps = [bar.timestamp for bar in bars]

    if timestamps != sorted(timestamps):
        issues.append(QualityIssue(
            "unsorted_timestamp", "Market bars are not ordered by timestamp.", True,
        ))

    duplicates = {timestamp for timestamp, count in Counter(timestamps).items() if count > 1}
    for timestamp in sorted(duplicates):
        issues.append(QualityIssue(
            "duplicate_timestamp", "Multiple bars share the same timestamp.", True, timestamp,
        ))

    missing_volume = False
    for bar in bars:
        prices = (bar.open, bar.high, bar.low, bar.close)
        if any(value <= 0 for value in prices):
            issues.append(QualityIssue(
                "non_positive_price", "OHLC prices must be positive.", True, bar.timestamp,
            ))
        elif bar.high < max(bar.open, bar.low, bar.close) or bar.low > min(
            bar.open, bar.high, bar.close,
        ):
            issues.append(QualityIssue(
                "invalid_ohlc", "High/low values do not contain open and close.", True, bar.timestamp,
            ))
        if bar.volume is None:
            missing_volume = True
        elif bar.volume < 0:
            issues.append(QualityIssue(
                "negative_volume", "Volume cannot be negative.", True, bar.timestamp,
            ))

    if missing_volume:
        issues.append(QualityIssue(
            "missing_volume", "One or more volume observations are unavailable.", False,
        ))

    if expected_latest_date is not None and bars:
        latest = _bar_date(max(bars, key=lambda bar: bar.timestamp).timestamp)
        if latest is not None and (expected_latest_date - latest).days > 3:
            issues.append(QualityIssue(
                "stale_data", "Latest market observation is stale.", False, latest.isoformat(),
            ))

    status = (
        "invalid" if any(issue.blocking for issue in issues)
        else "warning" if issues
        else "valid"
    )
    return DataQuality(status=status, issues=tuple(issues))

