from __future__ import annotations

import json
from datetime import date
from typing import Any

from src.historical_events.models import DetectedEvent, EvidenceItem, HistoricalEvent

OFFICIAL_SOURCES = ("hkex", "sec.gov", "nasdaq.com", "nyse.com", "港交所")
ANALYSIS_VERSION = "historical-event-analysis-v7"
MODEL_NAME = "deepseek/deepseek-v4-flash:online"


class EventAnalyzer:
    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm

    def analyze_batch(
        self,
        *,
        market: str,
        symbol: str,
        company_name: str,
        events: list[tuple[DetectedEvent, float | None]],
    ) -> list[HistoricalEvent]:
        if not events:
            return []
        llm = self._llm
        if llm is None:
            from src.providers.chat import ChatLLM

            llm = ChatLLM(model_name=MODEL_NAME)
        payload = {
            "current_date": date.today().isoformat(),
            "company_name": company_name,
            "symbol": symbol,
            "market": {"cn": "A股", "hk": "港股", "us": "美股"}.get(market, market),
            "events": [
                {
                    "start_date": event.start_date.isoformat(),
                    "end_date": event.end_date.isoformat(),
                    "direction": "上涨" if event.direction == "up" else "下跌",
                    "stock_return_pct": event.return_pct,
                    "benchmark_return_pct": benchmark_return,
                }
                for event, benchmark_return in events
            ],
        }
        try:
            response = llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是严谨的金融历史事件归因助手。根据已知历史事实，解释每个价格异动窗口内"
                            "该公司最可能发生了什么。只写最直接原因，不罗列无关新闻，不编造来源、数字"
                            "或事实；无法可靠确认时明确写原因不确定。返回一个JSON对象，格式为"
                            "请求中的current_date是系统当前日期，不得把早于当前日期的事件误判为未来。"
                            '{"items":[{"start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD",'
                            '"summary":"2至3句简短中文总结","driver_type":"简短类别",'
                            '"confidence":"高|中|低"}]}，不要使用Markdown。'
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                timeout=60,
            )
            parsed = json.loads(_strip_fences(str(response.content)))
            rows = parsed.get("items", []) if isinstance(parsed, dict) else []
        except Exception:
            rows = []

        by_dates = {
            (str(row.get("start_date")), str(row.get("end_date"))): row
            for row in rows if isinstance(row, dict)
        }
        results: list[HistoricalEvent] = []
        for event, benchmark_return in events:
            row = by_dates.get((event.start_date.isoformat(), event.end_date.isoformat()))
            summary = str(row.get("summary", "")).strip() if row else ""
            if not summary:
                results.append(self.analyze(
                    market=market, symbol=symbol, company_name=company_name,
                    event=event, evidence=[], benchmark_return=benchmark_return,
                ))
                continue
            confidence = str(row.get("confidence", "低")).strip()
            if confidence not in {"高", "中", "低"}:
                confidence = "低"
            results.append(self._event(
                market=market, symbol=symbol, company_name=company_name,
                event=event, benchmark_return=benchmark_return,
                driver_type=str(row.get("driver_type", "历史事件")).strip() or "历史事件",
                primary_driver=summary, narrative="", confidence=confidence,
                causality_note="该归因由 DeepSeek 基于历史知识生成，仅用于快速研究，可能存在遗漏或错误。",
            ))
        return results

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
        benchmark_symbol = {"cn": "000300.SH", "hk": "^HSI", "us": "^GSPC"}[market]
        relative = round(event.return_pct - benchmark_return, 2) if benchmark_return is not None else None
        if not evidence:
            return self._event(
                market=market, symbol=symbol, company_name=company_name, event=event,
                benchmark_return=benchmark_return,
                driver_type="原因未确认", primary_driver="原因未确认",
                narrative="未找到足够可靠的同期证据，无法确认本次波动的主要原因。",
                confidence="低",
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

    @staticmethod
    def _event(
        *, market: str, symbol: str, company_name: str, event: DetectedEvent,
        benchmark_return: float | None, driver_type: str, primary_driver: str,
        narrative: str, confidence: str, causality_note: str | None = None,
    ) -> HistoricalEvent:
        benchmark_symbol = {"cn": "000300.SH", "hk": "^HSI", "us": "^GSPC"}[market]
        relative = round(event.return_pct - benchmark_return, 2) if benchmark_return is not None else None
        market_context = (
            "个股事件驱动" if relative is not None and abs(relative) >= 5
            else "市场整体驱动" if relative is not None and abs(relative) < 5
            else "原因未确认"
        )
        values: dict[str, Any] = {}
        if causality_note:
            values["causality_note"] = causality_note
        return HistoricalEvent(
            **event.model_dump(),
            event_id=f"{market}-{symbol}-{event.start_date.isoformat()}-{event.end_date.isoformat()}",
            market=market, symbol=symbol, company_name=company_name,
            benchmark_symbol=benchmark_symbol, benchmark_return_pct=benchmark_return,
            relative_return_pct=relative, market_context=market_context,
            driver_type=driver_type, primary_driver=primary_driver, narrative=narrative,
            confidence=confidence, analysis_version=ANALYSIS_VERSION, **values,
        )


def _strip_fences(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
