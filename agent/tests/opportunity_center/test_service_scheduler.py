from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from src.opportunity_center.models import MarketContext, StockContext, StrategyContext
from src.opportunity_center.scheduler import OpportunityScheduler, due_market_dates
from src.opportunity_center.service import OpportunityService
from src.opportunity_center.storage import OpportunityStore


class FakeWatchlist:
    def __init__(self):
        self.rows = {"hk": ["0700", "9999"], "us": ["NVDA"]}

    def get(self, market):
        return self.rows[market]


class EmptyWatchlist:
    def get(self, market):
        return []


class FakeFeed:
    def __init__(self):
        self.refresh_calls = 0

    def refresh(self, now):
        self.refresh_calls += 1
        return []


class FakeCalibration:
    def __init__(self, fail=False):
        self.refresh_calls = 0
        self.fail = fail

    def refresh(self):
        self.refresh_calls += 1
        if self.fail:
            raise RuntimeError("calibration offline")
        return 0


def stock_loader(market, code):
    return StockContext(market=market, code=code, company_name=f"Name {code}")


def market_loader(market, code, as_of):
    if code == "9999":
        raise ValueError("missing price")
    return MarketContext(
        market=market, code=code, latest_price_date=as_of.isoformat(),
        trend_score=70, risk_score=80, trend_inputs={},
        risk_inputs={"annual_vol": .2, "downside_vol": .1, "max_drawdown": -.1, "return20": .02},
    )


def strategy_loader(market, code, as_of):
    return StrategyContext(
        strategy_name="donchian_breakout", strategy_label="唐奇安突破", action="entry",
        signal_date=as_of.isoformat(), current_weight=100,
        oos_total_return=.2, oos_max_drawdown=-.1, oos_sharpe=1.1,
        data_as_of=as_of.isoformat(),
    )


class NoopAnalyzer:
    def __init__(self, store):
        self.store = store

    def analyze(self, context, matches, analysis_date):
        return []


def service(tmp_path):
    feed = FakeFeed()
    calibration = FakeCalibration()
    instance = OpportunityService(
        store=OpportunityStore(tmp_path / "opportunities.db"),
        watchlist_store=FakeWatchlist(), feed_ingestor=feed,
        analyzer_factory=NoopAnalyzer, stock_context_loader=stock_loader,
        market_loader=market_loader, strategy_loader=strategy_loader,
        calibration_service=calibration,
    )
    return instance, feed


def test_job_refreshes_feed_once_and_isolates_stock_failure(tmp_path):
    svc, feed = service(tmp_path)
    job = svc.start_refresh(["hk", "us"], "manual", market_dates={"hk": "2026-06-29", "us": "2026-06-29"})
    asyncio.run(svc.run_job(job.job_id))

    items = svc.get_list().items
    assert feed.refresh_calls == 1
    assert {item.code for item in items} == {"0700", "9999", "NVDA"}
    assert next(item for item in items if item.code == "9999").level == "数据不足"
    assert svc.store.get_job(job.job_id).status == "completed"
    assert svc.calibration_service.refresh_calls == 1


def test_calibration_failure_does_not_discard_completed_snapshots(tmp_path):
    svc, _ = service(tmp_path)
    svc.calibration_service = FakeCalibration(fail=True)
    job = svc.start_refresh(["hk"], "manual", market_dates={"hk": "2026-06-29"})

    asyncio.run(svc.run_job(job.job_id))

    completed = svc.store.get_job(job.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert "calibration offline" in (completed.error or "")
    assert svc.get_list().items


def test_empty_watchlist_completes_without_refreshing_news(tmp_path):
    feed = FakeFeed()
    svc = OpportunityService(
        store=OpportunityStore(tmp_path / "opportunities.db"),
        watchlist_store=EmptyWatchlist(),
        feed_ingestor=feed,
    )
    job = svc.start_refresh(["hk", "us"], "scheduled")

    asyncio.run(svc.run_job(job.job_id))

    completed = svc.store.get_job(job.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.completed == 0
    assert feed.refresh_calls == 0


def test_active_job_is_reused_but_later_manual_job_is_new(tmp_path):
    svc, _ = service(tmp_path)
    first = svc.start_refresh(["hk"], "manual")
    assert svc.start_refresh(["us"], "manual").job_id == first.job_id
    asyncio.run(svc.run_job(first.job_id))
    second = svc.start_refresh(["hk"], "manual")
    assert second.job_id != first.job_id


def test_actionable_names_sort_first_and_once(tmp_path):
    svc, _ = service(tmp_path)
    job = svc.start_refresh(["hk", "us"], "manual", market_dates={"hk": date.today().isoformat(), "us": date.today().isoformat()})
    asyncio.run(svc.run_job(job.job_id))
    rows = svc.get_list().items
    assert rows[0].latest_action == "entry"
    assert len({(row.market, row.code) for row in rows}) == len(rows)


def test_hk_due_after_close_and_us_not_yet_due():
    now = datetime(2026, 6, 29, 9, 0, tzinfo=timezone.utc)
    assert due_market_dates(now) == {"hk": date(2026, 6, 29)}


def test_us_close_uses_new_york_dst():
    now = datetime(2026, 6, 29, 20, 30, tzinfo=timezone.utc)
    assert due_market_dates(now)["us"] == date(2026, 6, 29)


def test_scheduler_skips_completed_market_date(tmp_path):
    svc, _ = service(tmp_path)
    scheduler = OpportunityScheduler(svc)
    now = datetime(2026, 6, 29, 20, 30, tzinfo=timezone.utc)
    first = asyncio.run(scheduler.run_once(now))
    second = asyncio.run(scheduler.run_once(now))
    assert first is not None
    assert second is None
