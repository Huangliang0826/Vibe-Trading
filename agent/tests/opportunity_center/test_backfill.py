from __future__ import annotations

from datetime import date

import pandas as pd

from src.opportunity_center.backfill import OpportunityBackfillService, month_end_dates
from src.opportunity_center.models import MarketContext, StrategyContext
from src.opportunity_center.storage import OpportunityStore


class FixedWatchlist:
    def get(self, market):
        return {"hk": ["0700"], "us": ["NVDA"]}[market]


def frame(start="2021-01-01", end="2026-06-30", price=100.0):
    index = pd.bdate_range(start, end)
    return pd.DataFrame(
        {"open": price, "high": price, "low": price, "close": price, "volume": 1_000},
        index=index,
    )


def strategy_evaluator(price_frame, market, code, as_of):
    assert price_frame.index.max().date() >= as_of
    return StrategyContext(
        strategy_name="buy_and_hold", strategy_label="买入持有", action="hold",
        signal_date=as_of.isoformat(), current_weight=100,
        oos_total_return=0.1, oos_max_drawdown=-0.1, oos_sharpe=0.8,
        data_as_of=as_of.isoformat(),
    )


def market_evaluator(price_frame, market, code, as_of):
    trimmed = price_frame.loc[price_frame.index.date <= as_of]
    return MarketContext(
        market=market, code=code, latest_price_date=trimmed.index[-1].date().isoformat(),
        trend_score=70, risk_score=75,
        risk_inputs={"annual_vol": 0.2, "return20": 0.03},
    )


def test_month_end_dates_exclude_current_incomplete_month():
    assert month_end_dates(date(2026, 1, 1), date(2026, 4, 15)) == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
    ]


def test_backfill_loads_each_symbol_once_and_writes_fixed_source_outcomes(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    frames = {
        "0700.HK": frame(price=100), "NVDA": frame(price=200),
        "^HSI": frame(price=20_000), "^GSPC": frame(price=5_000),
    }
    calls: list[str] = []

    def loader(symbol, start_date, end_date):
        calls.append(symbol)
        return frames[symbol]

    service = OpportunityBackfillService(
        store=store, watchlist_store=FixedWatchlist(), price_loader=loader,
        strategy_evaluator=strategy_evaluator, market_evaluator=market_evaluator,
    )
    result = service.run(years=1, as_of=date(2026, 4, 15))

    assert calls == ["0700.HK", "^HSI", "NVDA", "^GSPC"]
    assert result.snapshot_count == 24
    assert result.error_count == 0
    assert len(store.list_snapshot_items()) == 24
    outcomes = store.list_outcomes()
    assert outcomes
    assert {row.sample_source for row in outcomes} == {"fixed_universe_backfill"}
    assert store.get_calibration_summary("top3").contains_fixed_universe_backfill is True


def test_backfill_is_idempotent(tmp_path):
    store = OpportunityStore(tmp_path / "opportunities.db")
    frames = {"0700.HK": frame(), "^HSI": frame(price=20_000)}

    class HKOnly:
        def get(self, market):
            return ["0700"] if market == "hk" else []

    service = OpportunityBackfillService(
        store=store, watchlist_store=HKOnly(), price_loader=lambda symbol, *_: frames[symbol],
        strategy_evaluator=strategy_evaluator, market_evaluator=market_evaluator,
    )
    service.run(years=1, as_of=date(2026, 3, 15))
    first_counts = (len(store.list_snapshot_items()), len(store.list_outcomes()))
    service.run(years=1, as_of=date(2026, 3, 15))

    assert (len(store.list_snapshot_items()), len(store.list_outcomes())) == first_counts
