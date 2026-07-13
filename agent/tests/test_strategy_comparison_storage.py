import pytest
from pydantic import ValidationError

from src.paper_trading.comparison_models import ComparisonStatus, StrategyComparisonCreate
from src.paper_trading.comparison_storage import StrategyComparisonStore


def _payload() -> StrategyComparisonCreate:
    return StrategyComparisonCreate(
        start_date="2020-01-01", end_date="2025-01-02",
        initial_capital=100_000, cost_bps=20,
    )


def test_comparison_rejects_windows_shorter_than_one_year():
    with pytest.raises(ValidationError):
        StrategyComparisonCreate(start_date="2025-01-01", end_date="2025-06-30")


def test_store_reuses_identical_completed_request(tmp_path):
    store = StrategyComparisonStore(tmp_path / "comparisons")
    first = store.create_or_reuse(_payload())
    first.status = ComparisonStatus.completed
    store.save(first)

    second = store.create_or_reuse(_payload())

    assert second.run_id == first.run_id
    assert second.cache_hit is True


def test_store_rejects_invalid_run_id(tmp_path):
    store = StrategyComparisonStore(tmp_path / "comparisons")
    with pytest.raises(ValueError, match="invalid comparison run id"):
        store.get("../../secret")
