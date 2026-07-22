from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from src.asset_management.portfolio_models import PortfolioBacktestRequest, PortfolioDefinition
from src.asset_management.portfolio_service import PortfolioBacktestService, TrackingStore
from src.paper_trading.models import PaperHolding
from src.paper_trading.strategies import _to_code


def _loader(codes: list[str], start: str, end: str):
    index = pd.bdate_range(start, end)
    if index.empty:
        index = pd.DatetimeIndex([pd.Timestamp(start)])
    result = {}
    for offset, code in enumerate(codes):
        if code in {"HKD=X", "CNY=X"}:
            close = np.full(len(index), 7.8 if code == "HKD=X" else 7.2)
        else:
            close = 100 * np.cumprod(np.full(len(index), 1.0003 + offset * 0.00001))
        result[code] = pd.DataFrame({"close": close}, index=index)
    return result


def _payload(model):
    return model.model_validate({
        "allocations": [
            {"symbol": "1810", "market": "hk", "name": "小米", "asset_type": "stock", "weight": 0.4},
            {"symbol": "SPY", "market": "us", "name": "SPY", "asset_type": "fund", "weight": 0.4},
            {"symbol": "CASH", "market": "cash", "name": "现金", "asset_type": "cash", "weight": 0.2},
        ],
        "initial_capital": 100_000,
        "installments": 10,
        "interval_days": 7,
        **({"years": 5, "rebalance_months": 3} if model is PortfolioBacktestRequest else {}),
    })


def test_shanghai_etf_symbol_uses_the_correct_yfinance_exchange():
    assert _to_code(PaperHolding(symbol="510300", market="cn", allocation_pct=1.0)) == "510300.SS"


def test_five_year_backtest_uses_ten_week_dca_and_preserves_capital():
    result = PortfolioBacktestService(loader=_loader).run(_payload(PortfolioBacktestRequest))

    assert result.installments == 10
    assert result.rebalances >= 18
    assert len(result.rebalance_dates) == result.rebalances
    assert result.rebalance_dates[0] > result.investment_completed_date
    first_gap = (
        pd.Timestamp(result.rebalance_dates[0]) - pd.Timestamp(result.investment_completed_date)
    ).days
    assert 89 <= first_gap <= 95
    assert result.curve[0].value >= 100_000
    assert result.final_value > 100_000
    assert len(result.annual_returns) >= 5
    assert result.annual_average_return > 0
    assert result.max_drawdown <= 0


def test_quarterly_rebalancing_resets_drift_after_investment_is_complete():
    def drifting_loader(codes: list[str], start: str, end: str):
        index = pd.bdate_range(start, end)
        result = {}
        for code in codes:
            if code == "HKD=X":
                close = np.full(len(index), 7.8)
            elif code.endswith(".HK"):
                close = 100 * np.cumprod(np.full(len(index), 1.003))
            else:
                close = np.full(len(index), 100.0)
            result[code] = pd.DataFrame({"close": close}, index=index)
        return result

    quarterly_request = _payload(PortfolioBacktestRequest).model_copy(update={
        "years": 1,
        "rebalance_months": 3,
    })
    no_rebalance_request = quarterly_request.model_copy(update={"rebalance_months": 12})
    service = PortfolioBacktestService(loader=drifting_loader)

    quarterly = service.run(quarterly_request)
    no_rebalance = service.run(no_rebalance_request)

    assert quarterly.rebalances == 3
    assert no_rebalance.rebalances == 0
    assert quarterly.final_value < no_rebalance.final_value


def test_cross_market_rebalancing_uses_a_common_real_trading_day():
    def staggered_loader(codes: list[str], start: str, end: str):
        all_days = pd.bdate_range(start, end)
        result = {}
        for code in codes:
            index = all_days[all_days.weekday == 2] if code == "SPY.US" else all_days
            close = np.full(len(index), 7.8 if code == "HKD=X" else 100.0)
            result[code] = pd.DataFrame({"close": close}, index=index)
        return result

    request = _payload(PortfolioBacktestRequest).model_copy(update={"years": 1})
    result = PortfolioBacktestService(loader=staggered_loader).run(request)

    assert result.rebalances > 0
    assert all(pd.Timestamp(value).weekday() == 2 for value in result.rebalance_dates)


def test_tracking_transactions_are_idempotent_and_persisted(tmp_path):
    store = TrackingStore(tmp_path / "tracking.db", loader=_loader)
    created = store.create(_payload(PortfolioDefinition))
    refreshed = store.refresh(created.tracker_id)

    assert created.tracker_id == refreshed.tracker_id
    assert created.completed_installments == refreshed.completed_installments == 1
    with store._session() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE tracker_id = ?", (created.tracker_id,)
        ).fetchone()[0]
        ledger_count = conn.execute(
            "SELECT COUNT(*) FROM cash_ledger WHERE tracker_id = ?", (created.tracker_id,)
        ).fetchone()[0]
        ledger_balance = sum(
            Decimal(row[0])
            for row in conn.execute(
                "SELECT amount_usd FROM cash_ledger WHERE tracker_id = ?", (created.tracker_id,)
            ).fetchall()
        )
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert count == 2
    assert ledger_count == 3
    assert abs(float(ledger_balance) - (100_000 - 8_000)) < 0.01
    assert journal.lower() == "wal"
    assert abs(refreshed.current_value - 100_000) < 100


def test_tracking_catches_up_each_due_tranche_once(tmp_path):
    store = TrackingStore(tmp_path / "tracking.db", loader=_loader)
    created = store.create(_payload(PortfolioDefinition))
    old_start = (date.today() - timedelta(days=21)).isoformat()
    with store._session() as conn:
        conn.execute("UPDATE trackers SET start_date = ? WHERE tracker_id = ?", (old_start, created.tracker_id))

    refreshed = store.refresh(created.tracker_id)
    store.refresh(created.tracker_id)

    assert refreshed.completed_installments == 4
    with store._session() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE tracker_id = ?", (created.tracker_id,)
        ).fetchone()[0]
        valuation_count = conn.execute(
            "SELECT COUNT(*) FROM valuations WHERE tracker_id = ?", (created.tracker_id,)
        ).fetchone()[0]
    assert count == 8
    assert valuation_count >= 15


def test_tracking_executes_each_due_quarterly_rebalance_once(tmp_path):
    store = TrackingStore(tmp_path / "tracking.db", loader=_loader)
    created = store.create(_payload(PortfolioDefinition))
    old_start = date.today() - timedelta(days=400)
    with store._session() as conn:
        conn.execute(
            "UPDATE trackers SET start_date = ?, created_at = ? WHERE tracker_id = ?",
            (old_start.isoformat(), old_start.isoformat(), created.tracker_id),
        )
        conn.execute(
            "UPDATE cash_ledger SET occurred_at = ? WHERE tracker_id = ? AND event_type = 'initial_deposit'",
            (old_start.isoformat(), created.tracker_id),
        )

    refreshed = store.refresh(created.tracker_id)
    repeated = store.refresh(created.tracker_id)

    assert refreshed.completed_installments == 10
    assert refreshed.completed_rebalances == repeated.completed_rebalances == 3
    assert refreshed.last_rebalance_date is not None
    assert refreshed.next_rebalance_date is not None
    with store._session() as conn:
        run_count = conn.execute(
            "SELECT COUNT(*) FROM rebalance_runs WHERE tracker_id = ?", (created.tracker_id,)
        ).fetchone()[0]
        trade_count = conn.execute(
            "SELECT COUNT(*) FROM rebalance_transactions WHERE tracker_id = ?",
            (created.tracker_id,),
        ).fetchone()[0]
        ledger_count = conn.execute(
            "SELECT COUNT(*) FROM cash_ledger WHERE tracker_id = ? AND event_type = 'rebalance'",
            (created.tracker_id,),
        ).fetchone()[0]
    assert run_count == 3
    assert trade_count == ledger_count == 6
