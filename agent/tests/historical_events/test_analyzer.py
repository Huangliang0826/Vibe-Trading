import json
from datetime import date

from src.historical_events.analyzer import MODEL_NAME, EventAnalyzer
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


class FakeLLM:
    def __init__(self):
        self.calls = []

    def chat(self, messages, timeout):
        self.calls.append((messages, timeout))
        return type("Response", (), {"content": """{
          "items": [{
            "start_date": "2024-05-14",
            "end_date": "2024-05-16",
            "summary": "腾讯公布季度业绩，盈利高于市场预期，推动股价上涨。",
            "driver_type": "财报业绩",
            "confidence": "高"
          }]
        }"""})()


def test_deepseek_batch_returns_short_model_summary_without_news_links():
    assert MODEL_NAME == "deepseek/deepseek-v4-flash:online"
    llm = FakeLLM()
    analyzer = EventAnalyzer(llm=llm)

    results = analyzer.analyze_batch(
        market="hk", symbol="0700", company_name="腾讯控股",
        events=[(detected(), 1.2)],
    )

    assert len(llm.calls) == 1
    assert llm.calls[0][1] == 60
    request_payload = json.loads(llm.calls[0][0][1]["content"])
    assert request_payload["current_date"] == date.today().isoformat()
    assert "不得把早于当前日期的事件误判为未来" in llm.calls[0][0][0]["content"]
    assert results[0].primary_driver == "腾讯公布季度业绩，盈利高于市场预期，推动股价上涨。"
    assert results[0].driver_type == "财报业绩"
    assert results[0].confidence == "高"
    assert results[0].evidence == []
    assert "DeepSeek" in results[0].causality_note
    assert results[0].analysis_version == "historical-event-analysis-v7"


def test_deepseek_batch_falls_back_to_unconfirmed_when_output_is_invalid():
    llm = type("InvalidLLM", (), {
        "chat": lambda self, messages, timeout: type("Response", (), {"content": "not json"})(),
    })()

    results = EventAnalyzer(llm=llm).analyze_batch(
        market="hk", symbol="0700", company_name="腾讯控股",
        events=[(detected(), 1.2)],
    )

    assert results[0].primary_driver == "原因未确认"
    assert results[0].confidence == "低"


def test_a_share_attribution_uses_csi300_benchmark():
    result = EventAnalyzer(llm=FakeLLM()).analyze_batch(
        market="cn", symbol="600519", company_name="贵州茅台",
        events=[(detected(), 0.8)],
    )[0]

    assert result.market == "cn"
    assert result.benchmark_symbol == "000300.SH"
