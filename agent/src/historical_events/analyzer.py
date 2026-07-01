from __future__ import annotations

from src.historical_events.models import DetectedEvent, EvidenceItem, HistoricalEvent

OFFICIAL_SOURCES = ("hkex", "sec.gov", "nasdaq.com", "nyse.com", "港交所")
ANALYSIS_VERSION = "historical-event-analysis-v5"


class EventAnalyzer:
    def analyze(
        self,
        *,
        market: str,
        symbol: str,
        company_name: str,
        event: DetectedEvent,
        evidence: list[EvidenceItem],
        benchmark_return: float | None,
    ) -> HistoricalEvent:
        event_id = f"{market}-{symbol}-{event.start_date.isoformat()}-{event.end_date.isoformat()}"
        benchmark_symbol = "^HSI" if market == "hk" else "^GSPC"
        relative = round(event.return_pct - benchmark_return, 2) if benchmark_return is not None else None
        if not evidence:
            return HistoricalEvent(
                **event.model_dump(), event_id=event_id, market=market, symbol=symbol,
                company_name=company_name, benchmark_symbol=benchmark_symbol,
                benchmark_return_pct=benchmark_return, relative_return_pct=relative,
                driver_type="原因未确认", primary_driver="原因未确认",
                narrative="未找到足够可靠的同期证据，无法确认本次波动的主要原因。",
                confidence="低",
                analysis_version=ANALYSIS_VERSION,
            )

        primary = evidence[0]
        official = any(source in primary.source.casefold() for source in OFFICIAL_SOURCES)
        market_context = (
            "个股事件驱动" if relative is not None and abs(relative) >= 5
            else "市场整体驱动" if relative is not None and abs(relative) < 5
            else "原因未确认"
        )
        return HistoricalEvent(
            **event.model_dump(), event_id=event_id, market=market, symbol=symbol,
            company_name=company_name, benchmark_symbol=benchmark_symbol,
            benchmark_return_pct=benchmark_return, relative_return_pct=relative,
            market_context=market_context, driver_type=primary.evidence_type,
            primary_driver=f"同期证据显示：{primary.title}",
            narrative=primary.snippet or "该证据与价格异动时间接近，建议结合原文核查。",
            confidence="高" if official or primary.evidence_type in {"财报", "公司公告"} else "中",
            evidence=evidence[:5],
            analysis_version=ANALYSIS_VERSION,
        )
