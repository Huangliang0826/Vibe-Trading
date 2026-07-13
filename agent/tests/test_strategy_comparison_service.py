import numpy as np
import pandas as pd

from src.paper_trading.comparison_models import (
    ComparisonStatus,
    StrategyComparisonCreate,
)
from src.paper_trading.comparison_service import run_strategy_comparison
from src.paper_trading.comparison_storage import StrategyComparisonStore


def _comparison_run(tmp_path):
    store = StrategyComparisonStore(tmp_path / "comparisons")
    run = store.create_or_reuse(StrategyComparisonCreate(
        start_date="2020-01-02", end_date="2025-01-03",
        initial_capital=100_000, cost_bps=20,
    ))
    return store, run


def _spy_loader(_start, _end):
    index = pd.bdate_range("2018-01-02", periods=1900)
    close = pd.Series(np.linspace(100, 250, len(index)), index=index)
    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close, "low": close, "close": close, "volume": 10_000_000,
    }, index=index)


def test_service_keeps_spy_results_when_momentum_data_fails(tmp_path):
    store, run = _comparison_run(tmp_path)

    result = run_strategy_comparison(
        run.run_id, store,
        universe_loader=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("panel down")),
        spy_loader=_spy_loader,
    )

    assert result.status == ComparisonStatus.partial
    assert [item.key for item in result.results] == [
        "spy_buy_hold", "spy_ma200", "defensive_momentum_v0",
    ]
    assert result.results[-1].status == "unavailable"
    assert result.survivorship_bias is True
    assert "panel down" in (result.results[-1].error or "")


def test_service_marks_whole_run_failed_when_spy_is_unavailable(tmp_path):
    store, run = _comparison_run(tmp_path)

    result = run_strategy_comparison(
        run.run_id, store,
        universe_loader=lambda *_args, **_kwargs: {},
        spy_loader=lambda *_args: (_ for _ in ()).throw(RuntimeError("SPY unavailable")),
    )

    assert result.status == ComparisonStatus.failed
    assert result.results == []
    assert "SPY unavailable" in (result.error or "")
