import csv
import json
from datetime import date
from types import SimpleNamespace

from src.analytics.quality_sources import (
    BacktestHistorySource,
    PaperTradingHistorySource,
    ScannerHistorySource,
)
from src.scanner.tracking import TrackingRecord, save_tracking


def _write_tracking(root, universe: str, as_of: str, **returns) -> None:
    save_tracking(
        [
            TrackingRecord(
                symbol="AAPL",
                score=0.8,
                asof=as_of,
                entry_price=100.0,
                **returns,
            )
        ],
        as_of,
        root=root,
        universe=universe,
    )


def _write_successful_backtest(path, *, total_return: float) -> None:
    artifacts = path / "artifacts"
    artifacts.mkdir(parents=True)
    (path / "state.json").write_text(
        json.dumps({"status": "success", "completed_at": "2026-07-12T11:00:00Z"}),
        encoding="utf-8",
    )
    with (artifacts / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["total_return", "trade_count"])
        writer.writeheader()
        writer.writerow({"total_return": total_return, "trade_count": 21})


def test_scanner_source_hides_unmatured_forward_returns(tmp_path):
    _write_tracking(
        tmp_path,
        "sp500",
        "2026-07-10",
        fwd_1d=1.0,
        fwd_5d=4.0,
    )

    result = ScannerHistorySource(tmp_path, universes=("sp500",)).read(
        date(2026, 7, 11),
        date(2026, 7, 12),
    )

    assert result.status == "available"
    assert any(event.metadata["horizon"] == "1d" for event in result.events)
    assert not any(event.metadata["horizon"] == "5d" for event in result.events)
    assert result.data_through == "2026-07-12"


def test_backtest_source_skips_corrupt_run_and_reports_partial(tmp_path):
    _write_successful_backtest(tmp_path / "good", total_return=0.2)
    broken = tmp_path / "broken"
    (broken / "artifacts").mkdir(parents=True)
    (broken / "state.json").write_text(
        json.dumps({"status": "success", "completed_at": "2026-07-12T11:00:00Z"}),
        encoding="utf-8",
    )
    (broken / "artifacts" / "metrics.csv").write_text("metric\nnot-a-number\n", encoding="utf-8")

    result = BacktestHistorySource(tmp_path).read(
        date(2026, 4, 15),
        date(2026, 7, 13),
    )

    assert result.status == "partial"
    assert result.records_scanned == 2
    assert result.events
    assert result.reason == "parse_errors"


def test_paper_source_reads_only_completed_runs_in_window():
    completed = SimpleNamespace(
        run_id="paper-1",
        status="completed",
        updated_at="2026-07-12T14:30:00Z",
        holdings=[SimpleNamespace(market="us")],
        experiment=SimpleNamespace(metric_version="backtest.metrics.v2"),
        metrics={"total_return": 0.15, "trade_count": 24},
    )
    running = SimpleNamespace(
        run_id="paper-2",
        status="running",
        updated_at="2026-07-12T15:30:00Z",
        holdings=[SimpleNamespace(market="us")],
        experiment=None,
        metrics=None,
    )
    store = SimpleNamespace(list_runs=lambda limit=500: [completed, running])

    result = PaperTradingHistorySource(store).read(
        date(2026, 7, 1),
        date(2026, 7, 13),
    )

    assert result.status == "available"
    assert result.records_scanned == 2
    assert {event.metadata["subject_id"] for event in result.events} == {"paper-1"}
