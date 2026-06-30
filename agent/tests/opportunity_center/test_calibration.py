from __future__ import annotations

import pandas as pd

from src.opportunity_center.calibration import (
    CALIBRATION_VERSION,
    OpportunityCalibrationService,
    compute_outcomes,
)
from src.opportunity_center.models import SCORE_VERSION, STRATEGY_VERSION, OpportunityItem
from src.opportunity_center.storage import OpportunityStore


def price_frame(dates, *, open_price=100.0, close_price=100.0):
    return pd.DataFrame(
        {"open": [open_price] * len(dates), "close": [close_price] * len(dates)},
        index=pd.DatetimeIndex(dates),
    )


def test_compute_outcomes_enters_next_session_and_exits_on_fifth_session_close():
    dates = pd.bdate_range("2026-06-01", periods=10)
    stock = price_frame(dates)
    benchmark = price_frame(dates, open_price=200, close_price=200)
    stock.loc[pd.Timestamp("2026-06-08"), "close"] = 110
    benchmark.loc[pd.Timestamp("2026-06-08"), "close"] = 208

    outcome = compute_outcomes(
        market="hk", code="0700", frame=stock, benchmark=benchmark,
        snapshot_date="2026-06-01", rank=1, is_top3=True, horizons=(5,),
    )[0]

    assert outcome.status == "completed"
    assert outcome.entry_date == "2026-06-02"
    assert outcome.entry_price == 100
    assert outcome.exit_date == "2026-06-08"
    assert outcome.stock_return == 0.10
    assert outcome.benchmark_return == 0.04
    assert outcome.excess_return == 0.06
    assert outcome.calibration_version == CALIBRATION_VERSION


def test_compute_outcomes_keeps_immature_horizon_pending():
    dates = pd.bdate_range("2026-06-01", periods=5)
    outcome = compute_outcomes(
        market="us", code="NVDA", frame=price_frame(dates),
        benchmark=price_frame(dates, open_price=200, close_price=200),
        snapshot_date="2026-06-01", rank=2, is_top3=True, horizons=(5,),
    )[0]

    assert outcome.status == "pending"
    assert outcome.entry_date == "2026-06-02"
    assert outcome.exit_date is None


def test_compute_outcomes_requires_exact_benchmark_dates_and_valid_prices():
    dates = pd.bdate_range("2026-06-01", periods=10)
    benchmark_dates = dates.delete(5)
    outcome = compute_outcomes(
        market="hk", code="0700", frame=price_frame(dates),
        benchmark=price_frame(benchmark_dates, open_price=200, close_price=200),
        snapshot_date="2026-06-01", rank=4, is_top3=False, horizons=(5,),
    )[0]

    assert outcome.status == "missing"
    assert "benchmark exit price" in (outcome.error or "")


def test_compute_outcomes_rejects_zero_entry_price():
    dates = pd.bdate_range("2026-06-01", periods=10)
    stock = price_frame(dates)
    stock.loc[pd.Timestamp("2026-06-02"), "open"] = 0
    outcome = compute_outcomes(
        market="us", code="AAPL", frame=stock,
        benchmark=price_frame(dates, open_price=200, close_price=200),
        snapshot_date="2026-06-01", rank=1, is_top3=True, horizons=(5,),
    )[0]

    assert outcome.status == "missing"
    assert "entry price" in (outcome.error or "")


def test_calibration_service_batches_symbol_data_and_skips_completed_results(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    store.upsert_snapshot(OpportunityItem(
        market="hk", code="0700", company_name="腾讯控股", snapshot_date="2026-01-02",
        score=80, level="优先关注", data_as_of="2026-01-02",
        score_version=SCORE_VERSION, strategy_version=STRATEGY_VERSION,
    ), trigger="scheduled")
    dates = pd.bdate_range("2026-01-02", periods=70)
    frames = {
        "0700.HK": price_frame(dates, open_price=100, close_price=110),
        "^HSI": price_frame(dates, open_price=200, close_price=208),
    }
    calls: list[str] = []

    def loader(symbol: str, start_date: str, end_date: str):
        calls.append(symbol)
        return frames[symbol]

    service = OpportunityCalibrationService(store, price_loader=loader)
    first = service.refresh(as_of=pd.Timestamp("2026-04-30").date())
    second = service.refresh(as_of=pd.Timestamp("2026-04-30").date())

    assert first == 3
    assert second == 0
    assert calls == ["0700.HK", "^HSI"]
    assert {row.status for row in store.list_outcomes()} == {"completed"}


def test_calibration_service_does_not_use_rows_after_as_of(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    store.upsert_snapshot(OpportunityItem(
        market="us", code="NVDA", company_name="NVIDIA", snapshot_date="2026-06-01",
        score=75, level="值得观察", data_as_of="2026-06-01",
        score_version=SCORE_VERSION, strategy_version=STRATEGY_VERSION,
    ), trigger="scheduled")
    dates = pd.bdate_range("2026-06-01", periods=70)
    frames = {
        "NVDA": price_frame(dates),
        "^GSPC": price_frame(dates, open_price=200, close_price=200),
    }
    service = OpportunityCalibrationService(store, price_loader=lambda symbol, *_: frames[symbol])

    service.refresh(as_of=pd.Timestamp("2026-06-05").date())

    assert {row.status for row in store.list_outcomes()} == {"pending"}
