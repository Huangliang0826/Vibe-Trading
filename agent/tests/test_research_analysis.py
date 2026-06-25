from __future__ import annotations

import pytest

from src.research_analysis.models import ResearchAnalysisReport, ResearchAnalysisStatus
from src.research_analysis.storage import DISCLAIMER, ResearchAnalysisStore, normalize_symbol


def test_normalize_symbol_supports_us_and_hk_tickers() -> None:
    assert normalize_symbol("AAPL").symbol == "AAPL"
    assert normalize_symbol("nvda", "us").symbol == "NVDA"
    assert normalize_symbol("00700", "hk").symbol == "0700.HK"
    assert normalize_symbol("9988.HK").symbol == "9988.HK"


@pytest.mark.parametrize("symbol", ["", "../AAPL", "AA PL", "$TSLA"])
def test_normalize_symbol_rejects_invalid_tickers(symbol: str) -> None:
    with pytest.raises(ValueError):
        normalize_symbol(symbol)


def _sample_report() -> ResearchAnalysisReport:
    return ResearchAnalysisReport(
        rating="buy",
        confidence=72,
        horizon="中期",
        summary="腾讯控股具备现金流韧性，护城河仍然清晰。",
        bull_case="游戏与广告业务改善，云业务利润率修复。",
        bear_case="监管扰动和宏观消费疲弱可能压制估值。",
        technical_view="价格位于主要均线附近，趋势需要继续确认。",
        fundamental_view="利润质量稳定，回购提供下方支撑。",
        sentiment_news_view="新闻情绪偏中性，市场关注 AI 资本开支。",
        risk_factors=["港股流动性波动", "政策预期变化"],
        suggested_action="分批观察，不追高。",
        disclaimer=DISCLAIMER,
    )


def test_store_writes_run_files_and_indexes_search(tmp_path) -> None:
    store = ResearchAnalysisStore(root=tmp_path / "research_analyses", db_path=tmp_path / "research.db")
    run = store.create_run(normalize_symbol("00700", "hk"), "2026-06-25")

    assert run.status == ResearchAnalysisStatus.queued
    run_dir = tmp_path / "research_analyses" / run.run_id
    assert (run_dir / "run.json").exists()
    assert (run_dir / "report.md").exists()
    assert (run_dir / "raw_decision.json").exists()
    assert (run_dir / "events.jsonl").exists()

    completed = store.complete_run(run.run_id, _sample_report(), {"source": "unit-test"}, {"engine": "test"})

    assert completed.status == ResearchAnalysisStatus.completed
    assert completed.rating == "buy"
    assert completed.analysis_config["engine"] == "test"
    assert "腾讯控股" in (run_dir / "report.md").read_text(encoding="utf-8")

    by_symbol = store.list_runs(symbol="0700.HK")
    by_rating = store.list_runs(rating="buy")
    by_keyword = store.list_runs(query="护城河")
    by_date = store.list_runs(date_filter="2026-06-25")

    assert [item.run_id for item in by_symbol] == [run.run_id]
    assert [item.run_id for item in by_rating] == [run.run_id]
    assert [item.run_id for item in by_keyword] == [run.run_id]
    assert [item.run_id for item in by_date] == [run.run_id]


def test_store_delete_removes_files_and_index(tmp_path) -> None:
    store = ResearchAnalysisStore(root=tmp_path / "research_analyses", db_path=tmp_path / "research.db")
    run = store.create_run(normalize_symbol("AAPL", "us"))

    assert store.delete_run(run.run_id) is True
    assert not (tmp_path / "research_analyses" / run.run_id).exists()
    assert store.get_run(run.run_id) is None
    assert store.list_runs(symbol="AAPL") == []
