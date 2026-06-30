"""Fixed-universe historical backfill for opportunity quality calibration."""

from __future__ import annotations

import argparse
import calendar
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Callable

import pandas as pd

from backtest.loaders.yfinance_loader import DataLoader as YFinanceLoader
from src.opportunity_center.calibration import HORIZONS, _normalize_frame, _ranking_key, compute_outcomes
from src.opportunity_center.market_context import _compute_market_context
from src.opportunity_center.models import Market, MarketContext, OpportunityDetail, StrategyContext
from src.opportunity_center.scoring import score_opportunity
from src.opportunity_center.storage import OpportunityStore
from src.opportunity_center.strategy_context import evaluate_frame
from src.paper_trading.hstech_best import normalize_best_strategy_symbol
from src.paper_trading.models import PaperHolding
from src.watchlist import WatchlistStore

PriceLoader = Callable[[str, str, str], pd.DataFrame]
StrategyEvaluator = Callable[[pd.DataFrame, Market, str, date], StrategyContext]
MarketEvaluator = Callable[[pd.DataFrame, Market, str, date], MarketContext]


@dataclass(frozen=True)
class BackfillResult:
    snapshot_count: int
    outcome_count: int
    error_count: int
    errors: list[str]


class OpportunityBackfillService:
    def __init__(
        self,
        *,
        store: OpportunityStore | None = None,
        watchlist_store: WatchlistStore | None = None,
        price_loader: PriceLoader | None = None,
        strategy_evaluator: StrategyEvaluator | None = None,
        market_evaluator: MarketEvaluator | None = None,
    ) -> None:
        self.store = store or OpportunityStore()
        self.watchlist_store = watchlist_store or WatchlistStore()
        self.price_loader = price_loader or _load_price_history
        self.strategy_evaluator = strategy_evaluator or _evaluate_strategy
        self.market_evaluator = market_evaluator or _evaluate_market

    def run(self, *, years: int = 2, as_of: date | None = None) -> BackfillResult:
        if years < 1 or years > 5:
            raise ValueError("years must be between 1 and 5")
        cutoff = as_of or date.today()
        start = date(cutoff.year - years, cutoff.month, 1)
        snapshots = month_end_dates(start, cutoff)
        load_start = (start - timedelta(days=3 * 366)).isoformat()
        load_end = (cutoff + timedelta(days=1)).isoformat()
        frames: dict[tuple[Market, str], pd.DataFrame] = {}
        benchmarks: dict[Market, pd.DataFrame] = {}
        errors: list[str] = []

        for market in ("hk", "us"):
            codes = self.watchlist_store.get(market)
            if not codes:
                continue
            for code in codes:
                symbol = _symbol(market, code)
                try:
                    frames[(market, code)] = _normalize_frame(self.price_loader(symbol, load_start, load_end))
                except Exception as exc:
                    errors.append(f"{market}:{code}: {exc}")
            benchmark_symbol = "^HSI" if market == "hk" else "^GSPC"
            try:
                benchmarks[market] = _normalize_frame(self.price_loader(benchmark_symbol, load_start, load_end))
            except Exception as exc:
                errors.append(f"{market}:{benchmark_symbol}: {exc}")

        generated: list[OpportunityDetail] = []
        previous_scores: dict[tuple[Market, str], float] = {}
        for snapshot in snapshots:
            for (market, code), price_frame in frames.items():
                try:
                    strategy = self.strategy_evaluator(price_frame, market, code, snapshot)
                    market_context = self.market_evaluator(price_frame, market, code, snapshot)
                    detail = score_opportunity(
                        company_name=code,
                        snapshot_date=snapshot.isoformat(),
                        strategy=strategy,
                        market_context=market_context,
                        news_impacts=[],
                        matched_news_count=1,
                        previous_score=previous_scores.get((market, code)),
                    )
                    detail.explanations.append("固定当前自选股历史回放，存在幸存者偏差")
                    generated.append(detail)
                    if detail.score is not None:
                        previous_scores[(market, code)] = detail.score
                    self.store.upsert_snapshot(
                        detail,
                        trigger="fixed-universe-backfill",
                        detail={
                            "news": [],
                            "explanations": detail.explanations,
                            "history_available": True,
                            "backfill_method": "fixed_current_watchlist",
                        },
                    )
                except Exception as exc:
                    errors.append(f"{snapshot}:{market}:{code}: {exc}")

        outcome_count = 0
        grouped: dict[str, list[OpportunityDetail]] = {}
        for detail in generated:
            if detail.score is not None and detail.level != "数据不足":
                grouped.setdefault(detail.snapshot_date, []).append(detail)
        for snapshot_date, details in grouped.items():
            details.sort(key=lambda item: _ranking_key(item, snapshot_date))
            for rank, detail in enumerate(details, start=1):
                benchmark = benchmarks.get(detail.market)
                price_frame = frames.get((detail.market, detail.code))
                if benchmark is None or price_frame is None:
                    continue
                for outcome in compute_outcomes(
                    market=detail.market,
                    code=detail.code,
                    frame=price_frame,
                    benchmark=benchmark,
                    snapshot_date=snapshot_date,
                    rank=rank,
                    is_top3=rank <= 3,
                    horizons=HORIZONS,
                ):
                    self.store.upsert_outcome(outcome.model_copy(update={"sample_source": "fixed_universe_backfill"}))
                    outcome_count += 1

        return BackfillResult(
            snapshot_count=len(generated),
            outcome_count=outcome_count,
            error_count=len(errors),
            errors=errors,
        )


def month_end_dates(start: date, as_of: date) -> list[date]:
    results: list[date] = []
    year, month = start.year, start.month
    while (year, month) < (as_of.year, as_of.month):
        results.append(date(year, month, calendar.monthrange(year, month)[1]))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return results


def _symbol(market: Market, code: str) -> str:
    _paper, yahoo, _display = normalize_best_strategy_symbol(code, market)
    return yahoo.replace(".US", "") if market == "us" else yahoo


def _evaluate_strategy(frame: pd.DataFrame, market: Market, code: str, as_of: date) -> StrategyContext:
    paper_symbol, _yahoo, _display = normalize_best_strategy_symbol(code, market)
    holding = PaperHolding(symbol=paper_symbol, market=market, allocation_pct=100.0)
    return evaluate_frame(frame, holding=holding, as_of=as_of).as_context()


def _evaluate_market(frame: pd.DataFrame, market: Market, code: str, as_of: date) -> MarketContext:
    _paper, _yahoo, display = normalize_best_strategy_symbol(code, market)
    return _compute_market_context(
        frame, market=market, code=display, as_of=as_of, valuation_percentile=None,
    )


def _load_price_history(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    frame = YFinanceLoader().fetch([symbol], start_date, end_date, interval="1D").get(symbol)
    if frame is None or frame.empty:
        raise ValueError(f"No price data fetched for {symbol}")
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill opportunity quality using the current watchlist")
    parser.add_argument("--years", type=int, default=2)
    args = parser.parse_args(argv)
    result = OpportunityBackfillService().run(years=args.years)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.snapshot_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
