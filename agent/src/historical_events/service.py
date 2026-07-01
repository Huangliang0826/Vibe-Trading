from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd

from src.historical_events.analyzer import ANALYSIS_VERSION, EventAnalyzer
from src.historical_events.detector import detect_events
from src.historical_events.evidence import EvidenceSearcher
from src.historical_events.models import HistoricalEvent, HistoricalEventRun
from src.historical_events.storage import HistoricalEventStore

Period = str
PriceLoader = Callable[[str, str, Period], pd.DataFrame]


class HistoricalEventService:
    def __init__(
        self,
        *,
        store: HistoricalEventStore | None = None,
        price_loader: PriceLoader | None = None,
        evidence_searcher: Any | None = None,
        analyzer: EventAnalyzer | None = None,
    ) -> None:
        self.store = store or HistoricalEventStore()
        self.price_loader = price_loader or _load_prices
        self.evidence_searcher = evidence_searcher or EvidenceSearcher()
        self.analyzer = analyzer or EventAnalyzer()
        self._active: dict[tuple[str, str, str], str] = {}

    def start_run(
        self, market: str, symbol: str, company_name: str, period: str, force: bool = False,
    ) -> HistoricalEventRun:
        if market not in {"hk", "us"}:
            raise ValueError("重大历史事件仅支持港股和美股")
        if period not in {"1Y", "3Y", "5Y", "ALL"}:
            raise ValueError("历史事件区间必须是 1Y、3Y、5Y 或 ALL")
        normalized = symbol.strip().upper()
        key = (market, normalized, period)
        active_id = self._active.get(key)
        if active_id:
            active = self.store.get_run(active_id)
            if active and active.status in {"pending", "running"}:
                return active
            self._active.pop(key, None)
        if not force:
            cached = self.store.find_completed_run(market, normalized, period, ANALYSIS_VERSION)
            if cached:
                return cached.model_copy(update={"cached": True})
        run = HistoricalEventRun(
            run_id=uuid.uuid4().hex, market=market, symbol=normalized,
            company_name=company_name.strip() or normalized, period=period,
            analysis_version=ANALYSIS_VERSION,
        )
        self._active[key] = run.run_id
        return self.store.save_run(run)

    def run(self, run_id: str) -> HistoricalEventRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError("historical event run not found")
        run = self._update(run, status="running", progress=10, stage="加载复权行情")
        try:
            prices = self.price_loader(run.market, run.symbol, run.period)
            if prices.empty:
                raise ValueError("没有可用的历史价格数据")
            asset_type = "etf" if _looks_like_etf(run.symbol, run.company_name) else "stock"
            detected = detect_events(prices, asset_type=asset_type)
            benchmark_symbol = "^HSI" if run.market == "hk" else "^GSPC"
            benchmark = self.price_loader(run.market, benchmark_symbol, run.period)
            run = self._update(run, progress=35, stage=f"识别到 {len(detected)} 个重大波动")
            for index, event in enumerate(detected):
                evidence = self.evidence_searcher.search(
                    run.market, run.symbol, run.company_name, event.start_date, event.end_date,
                )
                benchmark_return = _interval_return(benchmark, event.start_date, event.end_date)
                analyzed = self.analyzer.analyze(
                    market=run.market, symbol=run.symbol, company_name=run.company_name,
                    event=event, evidence=evidence, benchmark_return=benchmark_return,
                )
                self.store.save_event(analyzed)
                progress = 35 + round(60 * (index + 1) / max(len(detected), 1))
                run = self._update(run, progress=progress, stage=f"归因事件 {index + 1}/{len(detected)}")
            run = self._update(
                run, status="completed", progress=100, stage="分析完成", event_count=len(detected),
            )
        except Exception as exc:
            run = self._update(run, status="failed", stage="分析失败", error=str(exc))
        finally:
            self._active.pop((run.market, run.symbol, run.period), None)
        return run

    def get_run(self, run_id: str) -> HistoricalEventRun | None:
        return self.store.get_run(run_id)

    def list_events(self, market: str, symbol: str, period: str) -> list[HistoricalEvent]:
        start, end = _period_range(period)
        return self.store.list_events(
            market, symbol.strip().upper(), start.isoformat(), end.isoformat(),
            analysis_version=ANALYSIS_VERSION,
        )

    def _update(self, run: HistoricalEventRun, **values: Any) -> HistoricalEventRun:
        values["updated_at"] = datetime.now(timezone.utc)
        return self.store.save_run(run.model_copy(update=values))


def _period_range(period: str) -> tuple[date, date]:
    end = date.today()
    if period == "ALL":
        return date(1900, 1, 1), end
    years = {"1Y": 1, "3Y": 3, "5Y": 5}.get(period)
    if years is None:
        raise ValueError("历史事件区间必须是 1Y、3Y、5Y 或 ALL")
    try:
        start = end.replace(year=end.year - years)
    except ValueError:
        start = end.replace(year=end.year - years, day=28)
    return start, end


def _load_prices(market: str, symbol: str, period: str) -> pd.DataFrame:
    from backtest.correlation import infer_market
    from backtest.loaders.registry import resolve_loader

    start, end = _period_range(period)
    fetch_symbol = symbol
    if market == "hk" and symbol not in {"^HSI"} and symbol.isdigit():
        fetch_symbol = f"{int(symbol):04d}.HK"
    inferred = infer_market(fetch_symbol)
    loader = resolve_loader(inferred)
    result = loader.fetch(
        codes=[fetch_symbol], start_date=(start - timedelta(days=100)).isoformat(),
        end_date=end.isoformat(), interval="1D",
    )
    frame = result.get(fetch_symbol)
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["close"])
    return frame[["close"]].sort_index()


def _interval_return(frame: pd.DataFrame, start: date, end: date) -> float | None:
    if frame.empty:
        return None
    subset = frame.loc[(frame.index.date >= start) & (frame.index.date <= end), "close"]
    if len(subset) < 2:
        return None
    return round((float(subset.iloc[-1]) / float(subset.iloc[0]) - 1) * 100, 2)


def _looks_like_etf(symbol: str, company_name: str) -> bool:
    text = f"{symbol} {company_name}".casefold()
    return "etf" in text or "基金" in text or symbol in {"QQQ", "VGT", "URTH"}
