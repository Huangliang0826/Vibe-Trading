from pathlib import Path

import pandas as pd

from src.historical_events.models import EvidenceItem
from src.historical_events.service import HistoricalEventService, _load_prices
from src.historical_events.storage import HistoricalEventStore


class Searcher:
    calls = 0

    def search(self, market, symbol, company_name, start_date, end_date):
        self.calls += 1
        return [EvidenceItem(title="重大公告", url="https://example.com/a", source="hkexnews.hk", evidence_type="公司公告")]


class BatchAnalyzer:
    calls = 0

    def analyze_batch(self, *, market, symbol, company_name, events):
        self.calls += 1
        fallback = __import__("src.historical_events.analyzer", fromlist=["EventAnalyzer"]).EventAnalyzer()
        return [
            fallback.analyze(
                market=market, symbol=symbol, company_name=company_name,
                event=event, evidence=[], benchmark_return=benchmark_return,
            )
            for event, benchmark_return in events
        ]


def loader(market: str, symbol: str, period: str) -> pd.DataFrame:
    values = [100.0] * 46 + [109.0, 109.0]
    return pd.DataFrame({"close": values}, index=pd.date_range("2024-01-02", periods=len(values), freq="B"))


def test_service_runs_and_reuses_completed_period_cache(tmp_path: Path):
    searcher = Searcher()
    analyzer = BatchAnalyzer()
    service = HistoricalEventService(
        store=HistoricalEventStore(tmp_path / "events.db"),
        price_loader=loader, evidence_searcher=searcher, analyzer=analyzer,
    )

    first = service.start_run("hk", "0700", "腾讯控股", "1Y")
    duplicate = service.start_run("hk", "0700", "腾讯控股", "1Y")
    assert duplicate.run_id == first.run_id

    completed = service.run(first.run_id)
    cached = service.start_run("hk", "0700", "腾讯控股", "1Y")

    assert completed.status == "completed"
    assert completed.event_count == 1
    assert cached.status == "completed"
    assert cached.cached is True
    assert searcher.calls == 0
    assert analyzer.calls == 1
    assert completed.period == "5Y"

    three_year = service.start_run("hk", "0700", "腾讯控股", "3Y")
    five_year = service.start_run("hk", "0700", "腾讯控股", "5Y")
    assert three_year.run_id == completed.run_id
    assert five_year.run_id == completed.run_id
    assert three_year.cached is True


def test_all_history_only_analyzes_events_missing_from_five_year_cache(tmp_path: Path):
    analyzer = BatchAnalyzer()
    service = HistoricalEventService(
        store=HistoricalEventStore(tmp_path / "events.db"),
        price_loader=loader, analyzer=analyzer,
    )
    five_year = service.start_run("hk", "0700", "腾讯控股", "1Y")
    service.run(five_year.run_id)
    assert analyzer.calls == 1

    all_history = service.start_run("hk", "0700", "腾讯控股", "ALL")
    completed = service.run(all_history.run_id)

    assert completed.status == "completed"
    assert analyzer.calls == 1


def test_service_persists_detected_markers_before_deepseek_analysis(tmp_path: Path):
    store = HistoricalEventStore(tmp_path / "events.db")
    observed = []

    class InspectingAnalyzer(BatchAnalyzer):
        def analyze_batch(self, *, market, symbol, company_name, events):
            observed.extend(store.list_events(
                market, symbol, "1900-01-01", "2100-01-01",
                analysis_version="historical-event-analysis-v7",
            ))
            return super().analyze_batch(
                market=market, symbol=symbol, company_name=company_name, events=events,
            )

    service = HistoricalEventService(
        store=store, price_loader=loader, analyzer=InspectingAnalyzer(),
    )
    run = service.start_run("hk", "0700", "腾讯控股", "1Y")
    service.run(run.run_id)

    assert len(observed) == 1
    assert observed[0].primary_driver == "正在分析原因"


def test_service_supports_a_shares_with_csi300_benchmark(tmp_path: Path):
    calls = []

    def recording_loader(market, symbol, period):
        calls.append((market, symbol, period))
        return loader(market, symbol, period)

    service = HistoricalEventService(
        store=HistoricalEventStore(tmp_path / "events.db"),
        price_loader=recording_loader, analyzer=BatchAnalyzer(),
    )
    run = service.start_run("cn", "600519", "贵州茅台", "1Y")
    completed = service.run(run.run_id)

    assert completed.status == "completed"
    assert ("cn", "000300.SH", "5Y") in calls


def test_a_share_price_loader_does_not_misclassify_chinext(monkeypatch):
    resolved_markets = []

    class Loader:
        def fetch(self, codes, start_date, end_date, interval):
            index = pd.date_range("2025-01-02", periods=3, freq="B")
            return {codes[0]: pd.DataFrame({"close": [100.0, 101.0, 102.0]}, index=index)}

    def resolve(market):
        resolved_markets.append(market)
        return Loader()

    monkeypatch.setattr("backtest.loaders.registry.resolve_loader", resolve)

    result = _load_prices("cn", "300750", "1Y")

    assert not result.empty
    assert resolved_markets == ["a_share"]


def test_old_analysis_version_is_not_reused(tmp_path: Path):
    store = HistoricalEventStore(tmp_path / "events.db")
    from src.historical_events.models import HistoricalEventRun

    store.save_run(HistoricalEventRun(
        run_id="old", market="hk", symbol="0700", company_name="腾讯控股",
        period="1Y", status="completed", analysis_version="historical-event-analysis-v6",
    ))
    service = HistoricalEventService(store=store, price_loader=loader, evidence_searcher=Searcher())

    run = service.start_run("hk", "0700", "腾讯控股", "1Y")

    assert run.run_id != "old"
    assert run.analysis_version == "historical-event-analysis-v7"
