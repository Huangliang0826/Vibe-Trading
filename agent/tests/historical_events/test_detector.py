from __future__ import annotations

import pandas as pd

from src.historical_events.detector import detect_events


def prices(returns: list[float]) -> pd.DataFrame:
    values = [100.0]
    for value in returns:
        values.append(values[-1] * (1 + value))
    return pd.DataFrame(
        {"close": values},
        index=pd.date_range("2024-01-02", periods=len(values), freq="B"),
    )


def test_detects_one_day_stock_jump_at_eight_percent():
    frame = prices([0.0] * 45 + [0.081] + [0.0] * 3)

    events = detect_events(frame, asset_type="stock")

    assert len(events) == 1
    assert events[0].direction == "up"
    assert events[0].trigger_windows == [1]
    assert events[0].return_pct == 8.1


def test_detects_three_day_move_and_merges_same_direction_triggers():
    frame = prices([0.0] * 45 + [0.06, 0.06, 0.06, 0.03])

    events = detect_events(frame, asset_type="stock")

    assert len(events) == 1
    assert events[0].direction == "up"
    assert 3 in events[0].trigger_windows
    assert events[0].return_pct > 15


def test_opposite_direction_moves_remain_separate():
    frame = prices([0.0] * 45 + [0.09, -0.10])

    events = detect_events(frame, asset_type="stock")

    assert [event.direction for event in events] == ["up", "down"]


def test_etf_uses_lower_threshold():
    frame = prices([0.0] * 45 + [0.041])

    events = detect_events(frame, asset_type="etf")

    assert len(events) == 1
    assert events[0].return_pct == 4.1


def test_current_move_is_excluded_from_volatility_baseline():
    alternating = [0.01 if index % 2 else -0.01 for index in range(60)]
    frame = prices(alternating + [0.09])

    events = detect_events(frame, asset_type="stock")

    assert len(events) == 1
    assert events[0].volatility_filter_available is True


def test_short_history_uses_fixed_threshold_and_marks_filter_unavailable():
    frame = prices([0.0] * 5 + [-0.09])

    events = detect_events(frame, asset_type="stock")

    assert len(events) == 1
    assert events[0].volatility_filter_available is False
