from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.opportunity_center.strategy_context import _classify_action, evaluate_frame
from src.paper_trading.models import PaperHolding


def make_ohlcv(start: str, periods: int, closes: list[float] | None = None) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="B")
    close = pd.Series(closes or np.linspace(100.0, 220.0, periods), index=index, dtype=float)
    volume = pd.Series(np.linspace(1_000_000.0, 1_500_000.0, periods), index=index, dtype=float)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
        },
        index=index,
    )
    frame.index.name = "trade_date"
    return frame


def append_extreme_future_rows(frame: pd.DataFrame, periods: int) -> pd.DataFrame:
    last = frame.index[-1]
    future_index = pd.date_range(last + pd.offsets.BDay(1), periods=periods, freq="B")
    future_close = pd.Series(np.linspace(5000.0, 50.0, periods), index=future_index, dtype=float)
    future = pd.DataFrame(
        {
            "open": future_close,
            "high": future_close * 1.05,
            "low": future_close * 0.95,
            "close": future_close,
            "volume": pd.Series(50_000_000.0, index=future_index, dtype=float),
        },
        index=future_index,
    )
    future.index.name = "trade_date"
    return pd.concat([frame, future])


def test_strategy_context_ignores_rows_after_as_of():
    base = make_ohlcv("2020-01-01", periods=1700)
    mutated = append_extreme_future_rows(base, periods=30)
    holding = PaperHolding(symbol="0700", market="hk", allocation_pct=100)
    as_of = base.index[-1].date()

    first = evaluate_frame(base, holding=holding, as_of=as_of)
    second = evaluate_frame(mutated, holding=holding, as_of=as_of)

    assert second.selected_strategy == first.selected_strategy
    assert second.action == first.action
    assert second.oos_sharpe == pytest.approx(first.oos_sharpe)
    assert second.data_as_of == first.data_as_of == as_of.isoformat()


def test_evaluate_frame_selects_strategy_on_training_only(monkeypatch: pytest.MonkeyPatch):
    holding = PaperHolding(symbol="0700", market="hk", allocation_pct=100)
    training = np.linspace(100.0, 200.0, 252)
    oos = np.linspace(200.0, 50.0, 252)
    frame = make_ohlcv("2024-01-01", periods=504, closes=list(training) + list(oos))

    monkeypatch.setattr(
        "src.opportunity_center.strategy_context.STRATEGY_NAMES",
        ("train_winner", "flat_cash"),
    )
    monkeypatch.setattr(
        "src.opportunity_center.strategy_context.STRATEGY_LABELS",
        {"train_winner": "Train Winner", "flat_cash": "Flat Cash"},
    )
    monkeypatch.setattr("src.opportunity_center.strategy_context.strategy_params", lambda _name: {})

    def fake_signal_series(
        strategy_name: str,
        frame: pd.DataFrame,
        holding: PaperHolding,
        params: dict[str, object],
    ) -> pd.Series:
        if strategy_name == "train_winner":
            return pd.Series(1.0, index=frame.index)
        return pd.Series(0.0, index=frame.index)

    monkeypatch.setattr("src.opportunity_center.strategy_context._strategy_signal_series", fake_signal_series)

    result = evaluate_frame(frame, holding=holding, as_of=frame.index[-1].date())

    assert result.selected_strategy == "train_winner"
    assert result.strategy_label == "Train Winner"
    assert result.oos_total_return < 0
    assert result.current_weight == pytest.approx(100.0)


def test_evaluate_frame_uses_target_weights_not_forced_end_of_backtest_trade():
    holding = PaperHolding(symbol="0700", market="hk", allocation_pct=100)
    frame = make_ohlcv("2023-01-02", periods=700)

    result = evaluate_frame(frame, holding=holding, as_of=frame.index[-1].date(), strategy_names=("buy_and_hold",))

    assert result.selected_strategy == "buy_and_hold"
    assert result.action == "hold"
    assert result.current_weight == pytest.approx(100.0)
    assert result.signal_date == frame.index[-1].date().isoformat()


@pytest.mark.parametrize(
    ("previous_weight", "current_weight", "expected"),
    [
        (0.0, 1.0, "entry"),
        (0.5, 1.0, "add"),
        (1.0, 0.0, "exit"),
        (1.0, 1.0, "hold"),
        (0.0, 0.0, "wait"),
    ],
)
def test_classify_action_from_final_target_weight_change(
    previous_weight: float,
    current_weight: float,
    expected: str,
):
    assert _classify_action(previous_weight, current_weight) == expected


def test_evaluate_frame_requires_two_years_of_history():
    holding = PaperHolding(symbol="0700", market="hk", allocation_pct=100)
    frame = make_ohlcv("2025-01-01", periods=503)

    with pytest.raises(ValueError, match="504"):
        evaluate_frame(frame, holding=holding, as_of=date(2026, 12, 7))
