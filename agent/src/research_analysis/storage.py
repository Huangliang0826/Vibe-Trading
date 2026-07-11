"""Filesystem + SQLite persistence for research analysis runs."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from src.config.paths import get_runtime_root
from src.research_analysis.models import ResearchAnalysisReport, ResearchAnalysisRun, ResearchAnalysisStatus


DISCLAIMER = "仅供研究参考，不构成投资建议。市场有风险，决策需结合个人风险承受能力。"


@dataclass(frozen=True)
class NormalizedSymbol:
    symbol: str
    market: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_symbol(symbol: str, market: str = "auto") -> NormalizedSymbol:
    raw_input = symbol.strip().upper()
    if re.search(r"\s", raw_input):
        raise ValueError("symbol must not contain whitespace")
    raw = raw_input
    requested = (market or "auto").lower()
    if not raw:
        raise ValueError("symbol must not be blank")
    if requested not in {"auto", "us", "hk"}:
        raise ValueError("market must be one of auto/us/hk")

    hk_match = re.fullmatch(r"0?\d{4,5}(?:\.HK)?", raw)
    if requested == "hk" or raw.endswith(".HK") or hk_match:
        digits = re.sub(r"\D", "", raw.replace(".HK", ""))
        if not digits:
            raise ValueError("invalid Hong Kong ticker")
        return NormalizedSymbol(symbol=f"{int(digits):04d}.HK", market="hk")

    if requested == "us" or requested == "auto":
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", raw):
            raise ValueError("invalid US ticker")
        return NormalizedSymbol(symbol=raw, market="us")

    raise ValueError("invalid ticker")


def report_to_markdown(report: ResearchAnalysisReport) -> str:
    risks = "\n".join(f"- {item}" for item in report.risk_factors) or "- 暂无"
    return f"""# 投研分析报告

## 结论
- 操作倾向：{report.rating.upper()}
- 置信度：{report.confidence}/100
- 周期：{report.horizon}

{report.summary}

## 牛方观点
{report.bull_case}

## 熊方观点
{report.bear_case}

## 技术面
{report.technical_view}

## 基本面
{report.fundamental_view}

## 新闻与情绪
{report.sentiment_news_view}

## 主要风险
{risks}

## 建议动作
{report.suggested_action}

## 声明
{report.disclaimer}
""".strip() + "\n"


class ResearchAnalysisStore:
    def __init__(self, root: Path | None = None, db_path: Path | None = None) -> None:
        runtime_root = get_runtime_root()
        self.root = root or (runtime_root / "research_analyses")
        self.db_path = db_path or (runtime_root / "research_analyses.db")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits/rolls back and then always closes.

        A bare ``with self._connect()`` only manages the transaction, leaking
        the connection's file descriptors on every call.
        """
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._session() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    company_name TEXT,
                    rating TEXT,
                    confidence INTEGER,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    analysis_date TEXT NOT NULL,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_research_symbol ON runs(symbol);
                CREATE INDEX IF NOT EXISTS idx_research_rating ON runs(rating);
                CREATE INDEX IF NOT EXISTS idx_research_date ON runs(analysis_date);
            """)
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS runs_fts
                    USING fts5(run_id UNINDEXED, content)
                """)
            except sqlite3.OperationalError:
                pass

    def run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"research-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", run_id):
            raise ValueError("invalid run_id")
        return self.root / run_id

    def create_run(self, normalized: NormalizedSymbol, analysis_date: str | None = None) -> ResearchAnalysisRun:
        now = utc_now()
        run_id = f"research-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        run = ResearchAnalysisRun(
            run_id=run_id,
            symbol=normalized.symbol,
            market=normalized.market,
            analysis_date=analysis_date or date.today().isoformat(),
            created_at=now,
            updated_at=now,
            status=ResearchAnalysisStatus.queued,
            summary="等待后台分析开始",
        )
        path = self.run_dir(run_id)
        path.mkdir(parents=True, exist_ok=False)
        self._write_run_files(run, raw_decision=None, report_markdown="")
        self._upsert_index(run, "")
        self.append_event(run_id, "queued", "分析任务已创建")
        return run

    def get_run(self, run_id: str) -> ResearchAnalysisRun | None:
        path = self.run_dir(run_id) / "run.json"
        if not path.exists():
            return None
        try:
            return ResearchAnalysisRun.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def update_status(self, run_id: str, status: ResearchAnalysisStatus, summary: str = "", error: str | None = None) -> ResearchAnalysisRun:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError("run not found")
        run.status = status
        run.updated_at = utc_now()
        if summary:
            run.summary = summary
        run.error = error
        self._write_run_files(run, run.raw_decision, run.report_markdown)
        self._upsert_index(run, run.report_markdown)
        self.append_event(run_id, status.value, summary or status.value, error=error)
        return run

    def complete_run(
        self,
        run_id: str,
        report: ResearchAnalysisReport,
        raw_decision: Any,
        analysis_config: dict[str, Any] | None = None,
        report_markdown: str | None = None,
    ) -> ResearchAnalysisRun:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError("run not found")
        markdown = report_markdown or report_to_markdown(report)
        run.status = ResearchAnalysisStatus.completed
        run.updated_at = utc_now()
        run.rating = report.rating
        run.confidence = report.confidence
        run.summary = report.summary
        run.report = report
        run.report_markdown = markdown
        run.raw_decision = raw_decision
        run.analysis_config = analysis_config or {}
        run.error = None
        self._write_run_files(run, raw_decision, markdown)
        self._upsert_index(run, markdown)
        self.append_event(run_id, "completed", "分析完成")
        return run

    def update_company_name(self, run_id: str, company_name: str) -> None:
        run = self.get_run(run_id)
        if run is None:
            return
        run.company_name = company_name
        run.updated_at = utc_now()
        self._write_run_files(run, run.raw_decision, run.report_markdown)
        with self._session() as conn:
            conn.execute("UPDATE runs SET company_name = ? WHERE run_id = ?", (company_name, run_id))

    def fail_run(self, run_id: str, message: str) -> ResearchAnalysisRun:
        return self.update_status(run_id, ResearchAnalysisStatus.failed, summary="分析失败", error=message)

    def list_runs(
        self,
        *,
        symbol: str | None = None,
        market: str | None = None,
        rating: str | None = None,
        query: str | None = None,
        date_filter: str | None = None,
        limit: int = 50,
    ) -> list[ResearchAnalysisRun]:
        where: list[str] = []
        params: list[Any] = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        if market and market != "all":
            where.append("market = ?")
            params.append(market)
        if rating and rating != "all":
            where.append("rating = ?")
            params.append(rating)
        if date_filter:
            where.append("analysis_date = ?")
            params.append(date_filter)
        join = ""
        if query:
            join = "JOIN runs_fts ON runs_fts.run_id = runs.run_id"
            where.append("runs_fts.content LIKE ?")
            params.append(f"%{query.strip()}%")
        sql = f"SELECT runs.run_id FROM runs {join}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 200)))
        with self._session() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[ResearchAnalysisRun] = []
        for row in rows:
            run = self.get_run(row["run_id"])
            if run:
                out.append(run)
        return out

    def delete_run(self, run_id: str) -> bool:
        path = self.run_dir(run_id)
        existed = path.exists()
        if existed:
            shutil.rmtree(path, ignore_errors=True)
        with self._session() as conn:
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            try:
                conn.execute("DELETE FROM runs_fts WHERE run_id = ?", (run_id,))
            except sqlite3.OperationalError:
                pass
        return existed

    def append_event(self, run_id: str, event: str, message: str, **extra: Any) -> None:
        path = self.run_dir(run_id) / "events.jsonl"
        payload = {"ts": utc_now(), "event": event, "message": message, **extra}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _write_run_files(self, run: ResearchAnalysisRun, raw_decision: Any, report_markdown: str) -> None:
        path = self.run_dir(run.run_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "run.json").write_text(run.model_dump_json(indent=2), encoding="utf-8")
        (path / "report.md").write_text(report_markdown or run.summary or "", encoding="utf-8")
        (path / "raw_decision.json").write_text(
            json.dumps(raw_decision if raw_decision is not None else {}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _upsert_index(self, run: ResearchAnalysisRun, report_markdown: str) -> None:
        with self._session() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs
                (run_id, symbol, market, company_name, rating, confidence, status, summary,
                 created_at, updated_at, analysis_date, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.symbol,
                    run.market,
                    run.company_name,
                    run.rating,
                    run.confidence,
                    run.status.value if hasattr(run.status, "value") else run.status,
                    run.summary,
                    run.created_at,
                    run.updated_at,
                    run.analysis_date,
                    run.error,
                ),
            )
            try:
                conn.execute("DELETE FROM runs_fts WHERE run_id = ?", (run.run_id,))
                content = " ".join([
                    run.symbol,
                    run.market,
                    run.rating or "",
                    run.summary or "",
                    report_markdown or "",
                ])
                conn.execute("INSERT INTO runs_fts (run_id, content) VALUES (?, ?)", (run.run_id, content))
            except sqlite3.OperationalError:
                pass

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = re.findall(r"[a-zA-Z0-9_.-]{2,}|[\u4e00-\u9fff\u3400-\u4dbf]", query)
        return " OR ".join(f'"{t}"' for t in tokens) if tokens else '""'


def fallback_report(symbol: str, raw_text: str, structured: bool = False) -> ResearchAnalysisReport:
    text = raw_text or ""
    lowered = text.lower()
    rating: str = "hold"
    if any(word in lowered for word in ["strong buy", "buy", "bullish", "看多", "买入"]):
        rating = "buy"
    if any(word in lowered for word in ["sell", "bearish", "看空", "卖出"]):
        rating = "sell"
    summary = text.strip().splitlines()[0][:500] if text.strip() else f"{symbol} 分析完成，但未能解析结构化报告。"
    return ResearchAnalysisReport(
        rating=rating,  # type: ignore[arg-type]
        confidence=55,
        horizon="中期",
        summary=summary,
        bull_case="详见 TradingAgents 原始输出。",
        bear_case="详见 TradingAgents 原始输出。",
        technical_view="详见 TradingAgents 原始输出。",
        fundamental_view="详见 TradingAgents 原始输出。",
        sentiment_news_view="详见 TradingAgents 原始输出。",
        risk_factors=["LLM 输出未完全结构化", "数据源可能存在延迟或缺失"],
        suggested_action="仅作为研究观点参考，不直接作为交易指令。",
        disclaimer=DISCLAIMER,
        structured=structured,
    )
