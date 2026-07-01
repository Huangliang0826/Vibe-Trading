from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.historical_events.models import AssetType, DetectedEvent, EventDirection

DETECTOR_VERSION = "major-move-v1"
WINDOWS = (1, 3, 5)
THRESHOLDS = {
    "stock": {1: 0.08, 3: 0.15, 5: 0.20},
    "etf": {1: 0.04, 3: 0.07, 5: 0.10},
}


@dataclass(frozen=True)
class _Candidate:
    start_index: int
    end_index: int
    direction: EventDirection
    return_value: float
    window: int
    volatility_filter_available: bool


def detect_events(frame: pd.DataFrame, asset_type: AssetType = "stock") -> list[DetectedEvent]:
    if asset_type not in THRESHOLDS:
        raise ValueError(f"unsupported asset type: {asset_type}")
    if "close" not in frame.columns:
        raise ValueError("price frame must contain close")

    clean = frame[["close"]].copy()
    clean["close"] = pd.to_numeric(clean["close"], errors="coerce")
    clean = clean.dropna().sort_index()
    if clean.index.has_duplicates:
        clean = clean[~clean.index.duplicated(keep="last")]
    candidates: list[_Candidate] = []

    for window in WINDOWS:
        returns = clean["close"].pct_change(window, fill_method=None)
        threshold = THRESHOLDS[asset_type][window]
        for end_index in range(window, len(clean)):
            value = float(returns.iloc[end_index])
            if pd.isna(value) or abs(value) < threshold:
                continue
            history = returns.iloc[max(window, end_index - 60):end_index].dropna()
            filter_available = len(history) >= 40
            if filter_available:
                sigma = float(history.std(ddof=1))
                if sigma > 0 and abs(value) < 2.5 * sigma:
                    continue
            candidates.append(
                _Candidate(
                    start_index=end_index - window,
                    end_index=end_index,
                    direction="up" if value > 0 else "down",
                    return_value=value,
                    window=window,
                    volatility_filter_available=filter_available,
                )
            )

    candidates.sort(key=lambda item: (item.end_index, item.start_index, item.window))
    groups: list[list[_Candidate]] = []
    for candidate in candidates:
        if (
            groups
            and groups[-1][0].direction == candidate.direction
            and candidate.start_index <= max(item.end_index for item in groups[-1]) + 5
        ):
            groups[-1].append(candidate)
        else:
            groups.append([candidate])

    events: list[DetectedEvent] = []
    for group in groups:
        strongest = max(group, key=lambda item: abs(item.return_value))
        events.append(
            DetectedEvent(
                start_date=pd.Timestamp(clean.index[min(item.start_index for item in group)]).date(),
                end_date=pd.Timestamp(clean.index[max(item.end_index for item in group)]).date(),
                direction=group[0].direction,
                return_pct=round(strongest.return_value * 100, 2),
                trigger_windows=sorted({item.window for item in group}),
                volatility_filter_available=all(item.volatility_filter_available for item in group),
            )
        )
    return events
