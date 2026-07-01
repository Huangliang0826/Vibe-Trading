from pathlib import Path

import pandas as pd

from src.historical_events.models import EvidenceItem
from src.historical_events.service import HistoricalEventService
from src.historical_events.storage import HistoricalEventStore


class Searcher:
    calls = 0

    def search(self, market, symbol, company_name, start_date, end_date):
        self.calls += 1
        return [EvidenceItem(title="重大公告", url="https://example.com/a", source="hkexnews.hk", evidence_type="公司公告")]


def loader(market: str, symbol: str, period: str) -> pd.DataFrame:
    values = [100.0] * 46 + [109.0, 109.0]
    return pd.DataFrame({"close": values}, index=pd.date_range("2024-01-02", periods=len(values), freq="B"))


def test_service_runs_and_reuses_completed_period_cache(tmp_path: Path):
    searcher = Searcher()
    service = HistoricalEventService(
        store=HistoricalEventStore(tmp_path / "events.db"),
        price_loader=loader, evidence_searcher=searcher,
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
    assert searcher.calls == 1


def test_service_rejects_a_shares(tmp_path: Path):
    service = HistoricalEventService(store=HistoricalEventStore(tmp_path / "events.db"), price_loader=loader)

    try:
        service.start_run("cn", "600519", "贵州茅台", "1Y")
    except ValueError as exc:
        assert "仅支持港股和美股" in str(exc)
    else:
        raise AssertionError("expected unsupported market error")


def test_old_analysis_version_is_not_reused(tmp_path: Path):
    store = HistoricalEventStore(tmp_path / "events.db")
    from src.historical_events.models import HistoricalEventRun

    store.save_run(HistoricalEventRun(
        run_id="old", market="hk", symbol="0700", company_name="腾讯控股",
        period="1Y", status="completed", analysis_version="historical-event-analysis-v4",
    ))
    service = HistoricalEventService(store=store, price_loader=loader, evidence_searcher=Searcher())

    run = service.start_run("hk", "0700", "腾讯控股", "1Y")

    assert run.run_id != "old"
    assert run.analysis_version == "historical-event-analysis-v5"
