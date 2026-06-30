"""Refresh orchestration for daily watchlist opportunity snapshots."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from src.opportunity_center.feeds import FeedIngestor
from src.opportunity_center.market_context import load_market_context
from src.opportunity_center.matching import build_stock_context, match_articles
from src.opportunity_center.models import (
    SCORE_VERSION,
    STRATEGY_VERSION,
    DimensionScores,
    Market,
    OpportunityDetail,
    OpportunityList,
    RefreshJob,
    StockContext,
)
from src.opportunity_center.news_analysis import NewsAnalyzer
from src.opportunity_center.scoring import score_opportunity
from src.opportunity_center.storage import OpportunityStore
from src.opportunity_center.strategy_context import evaluate_strategy_context
from src.paper_trading.hstech_best import normalize_best_strategy_symbol
from src.watchlist import WatchlistStore

_REFRESH_LOCK = asyncio.Lock()
ACTIONABLE = {"entry", "add", "exit", "risk_exit"}


@dataclass(frozen=True)
class _JobSpec:
    market_dates: dict[Market, str]
    force: bool


class OpportunityService:
    def __init__(
        self,
        *,
        store: OpportunityStore | None = None,
        watchlist_store: WatchlistStore | None = None,
        feed_ingestor: Any | None = None,
        analyzer_factory: Callable[[OpportunityStore], Any] = NewsAnalyzer,
        stock_context_loader: Callable[[Market, str], StockContext] | None = None,
        market_loader: Callable[[Market, str, date], Any] = load_market_context,
        strategy_loader: Callable[[Market, str, date], Any] = evaluate_strategy_context,
    ) -> None:
        self.store = store or OpportunityStore()
        self.watchlist_store = watchlist_store or WatchlistStore()
        self.feed_ingestor = feed_ingestor or FeedIngestor(
            self.store, Path(__file__).with_name("sources.json")
        )
        self.analyzer_factory = analyzer_factory
        self.stock_context_loader = stock_context_loader or _load_stock_context
        self.market_loader = market_loader
        self.strategy_loader = strategy_loader
        self._job_specs: dict[str, _JobSpec] = {}

    def start_refresh(
        self,
        markets: list[Market],
        trigger: str,
        force: bool = False,
        *,
        market_dates: dict[Market, str] | None = None,
    ) -> RefreshJob:
        active = self.store.get_active_job()
        if active is not None:
            return active
        normalized = list(dict.fromkeys(markets))
        if not normalized or any(market not in {"hk", "us"} for market in normalized):
            raise ValueError("markets must contain hk and/or us")
        dates = market_dates or {market: date.today().isoformat() for market in normalized}
        total = sum(len(self.watchlist_store.get(market)) for market in normalized)
        job_id = f"opportunity-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        job = self.store.create_job(
            job_id=job_id,
            markets=normalized,
            market_dates=dates,
            trigger=trigger,
            total=total,
        )
        if job.job_id == job_id:
            self._job_specs[job_id] = _JobSpec(market_dates=dates, force=force)
        return job

    async def run_job(self, job_id: str) -> None:
        async with _REFRESH_LOCK:
            job = self.store.get_job(job_id)
            if job is None:
                raise ValueError("refresh job not found")
            if job.status in {"completed", "failed"}:
                return
            spec = self._job_specs.get(job_id)
            if spec is None:
                fallback_dates = {market: date.today().isoformat() for market in job.markets}
                spec = _JobSpec(fallback_dates, False)
            self.store.update_job(job_id, status="running", completed=0)
            errors: list[str] = []
            completed = 0
            try:
                now = datetime.now(timezone.utc)
                await asyncio.to_thread(self.feed_ingestor.refresh, now)
                since = (now - timedelta(days=7)).isoformat(timespec="seconds").replace("+00:00", "Z")
                articles = await asyncio.to_thread(self.store.find_recent_articles, since=since, limit=500)
                try:
                    analyzer = self.analyzer_factory(self.store)
                except Exception:
                    analyzer = None

                for market in job.markets:
                    market_date = spec.market_dates.get(market, date.today().isoformat())
                    as_of = date.fromisoformat(market_date)
                    for code in self.watchlist_store.get(market):
                        error: str | None = None
                        try:
                            stock = await asyncio.to_thread(self.stock_context_loader, market, code)
                            market_context = await asyncio.to_thread(self.market_loader, market, code, as_of)
                            try:
                                strategy = await asyncio.to_thread(self.strategy_loader, market, code, as_of)
                            except Exception as exc:
                                strategy = None
                                error = f"strategy: {exc}"
                            matches = match_articles(stock, articles)
                            for match in matches:
                                self.store.save_matches(match.article.article_id, [{
                                    "market": market,
                                    "code": code,
                                    "match_level": match.match_level,
                                    "confidence": match.confidence,
                                }])
                            impacts = []
                            if analyzer is not None and matches:
                                try:
                                    impacts = await asyncio.to_thread(analyzer.analyze, stock, matches, market_date)
                                except Exception as exc:
                                    error = _join_error(error, f"news analysis: {exc}")
                            stale = market_context.latest_price_date < market_date
                            detail = score_opportunity(
                                company_name=stock.company_name,
                                snapshot_date=market_date,
                                strategy=strategy,
                                market_context=market_context,
                                news_impacts=impacts,
                                matched_news_count=len(matches),
                                stale=stale,
                                history_available=bool(self.store.get_history(market, code, limit=1)),
                            )
                            if error:
                                detail.explanations.append(error)
                                detail.degraded = True
                        except Exception as exc:
                            error = str(exc)
                            detail = _failed_detail(market, code, market_date, error)
                        self.store.upsert_snapshot(detail, trigger=job.trigger, detail={
                            "news": [item.model_dump(mode="json") for item in detail.news],
                            "explanations": detail.explanations,
                            "history_available": detail.history_available,
                        })
                        if error:
                            errors.append(f"{market}:{code}: {error}")
                        completed += 1
                        self.store.update_job(job_id, status="running", completed=completed, error="; ".join(errors) or None)
                self.store.update_job(job_id, status="completed", completed=completed, error="; ".join(errors) or None)
            except Exception as exc:
                self.store.update_job(job_id, status="failed", completed=completed, error=str(exc))
            finally:
                self._job_specs.pop(job_id, None)

    def get_list(self, *, market: str | None = None, signal: str | None = None, level: str | None = None) -> OpportunityList:
        items = self.store.list_latest(market=market, signal=signal, level=level, limit=500)
        cutoff = date.today() - timedelta(days=7)

        def key(item):
            actionable = item.latest_action in ACTIONABLE and _date_or_min(item.signal_date) >= cutoff
            score = item.score if item.score is not None else -1.0
            return (0 if actionable else 1, -_date_ordinal(item.signal_date) if actionable else 0, -score)

        items.sort(key=key)
        latest = max((item.data_as_of for item in items), default=None)
        return OpportunityList(
            items=items,
            latest_success_at=latest,
            active_job=self.store.get_active_job(),
            last_refresh_error=self.store.get_last_refresh_error(),
        )

    def get_detail(self, market: str, code: str, snapshot_date: str | None = None):
        return self.store.get_detail(market, code, snapshot_date)

    def get_history(self, market: str, code: str, limit: int = 30):
        return self.store.get_history(market, code, limit=limit)


def _load_stock_context(market: Market, code: str) -> StockContext:
    profile: dict[str, Any] = {}
    name = code.upper()
    try:
        import yfinance as yf

        paper_code, yahoo_code, _display = normalize_best_strategy_symbol(code, market)
        profile = dict(yf.Ticker(yahoo_code if market == "hk" else paper_code).info or {})
        name = str(profile.get("shortName") or profile.get("longName") or name)
    except Exception:
        pass
    return build_stock_context(market, code.upper(), name, profile)


def _failed_detail(market: Market, code: str, snapshot_date: str, error: str) -> OpportunityDetail:
    return OpportunityDetail(
        market=market,
        code=code.upper(),
        company_name=code.upper(),
        snapshot_date=snapshot_date,
        score=None,
        level="数据不足",
        primary_reason="价格或策略数据不可用",
        risk_reasons=[error],
        dimensions=DimensionScores(),
        data_as_of=snapshot_date,
        stale=True,
        degraded=True,
        missing_dimensions=["strategy", "trend", "risk", "news", "valuation"],
        score_version=SCORE_VERSION,
        strategy_version=STRATEGY_VERSION,
        explanations=[error],
    )


def _join_error(current: str | None, value: str) -> str:
    return f"{current}; {value}" if current else value


def _date_or_min(value: str | None) -> date:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return date.min


def _date_ordinal(value: str | None) -> int:
    return _date_or_min(value).toordinal()
