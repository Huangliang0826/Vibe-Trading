from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone

from .models import AnalyticsEvent


def make_quality_event(
    *,
    subject_type: str,
    subject_id: str,
    market: str,
    horizon: str,
    regime: str,
    metric_name: str,
    metric_value: float | None,
    sample_count: int,
    formula_version: str,
    as_of: date,
    interval_low: float | None = None,
    interval_high: float | None = None,
    reason: str | None = None,
) -> AnalyticsEvent:
    identity = {
        "as_of": as_of.isoformat(),
        "formula_version": formula_version,
        "horizon": horizon,
        "market": market,
        "metric_name": metric_name,
        "regime": regime,
        "subject_id": subject_id,
        "subject_type": subject_type,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    event_id = f"quality-{hashlib.sha256(canonical.encode()).hexdigest()[:32]}"
    metadata = {
        **identity,
        "metric_value": metric_value,
        "sample_count": sample_count,
        "interval_low": interval_low,
        "interval_high": interval_high,
        "reason": reason,
    }
    return AnalyticsEvent(
        event_id=event_id,
        kind="quality",
        occurred_at=datetime.combine(as_of, time.min, tzinfo=timezone.utc),
        feature=subject_type,
        action=metric_name,
        outcome="success" if metric_value is not None else "unknown",
        metadata=metadata,
    )
