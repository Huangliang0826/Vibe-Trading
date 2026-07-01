from src.historical_events.analyzer import EventAnalyzer
from src.historical_events.models import DetectedEvent, EvidenceItem


def detected() -> DetectedEvent:
    return DetectedEvent(
        start_date="2024-05-14", end_date="2024-05-16",
        direction="up", return_pct=18.6, trigger_windows=[3],
    )


def test_missing_evidence_never_invents_a_cause():
    result = EventAnalyzer().analyze(
        market="hk", symbol="0700", company_name="腾讯控股",
        event=detected(), evidence=[], benchmark_return=1.2,
    )

    assert result.driver_type == "原因未确认"
    assert result.primary_driver == "原因未确认"
    assert result.confidence == "低"


def test_official_results_are_used_as_traceable_primary_evidence():
    evidence = [EvidenceItem(
        title="腾讯公布第一季度业绩", url="https://example.com/results",
        snippet="收入及净利润高于市场预期", source="港交所",
        published_at="2024-05-14", evidence_type="财报",
    )]

    result = EventAnalyzer().analyze(
        market="hk", symbol="0700", company_name="腾讯控股",
        event=detected(), evidence=evidence, benchmark_return=1.2,
    )

    assert result.driver_type == "财报"
    assert result.confidence == "高"
    assert result.evidence[0].url == "https://example.com/results"
    assert "腾讯公布第一季度业绩" in result.primary_driver
