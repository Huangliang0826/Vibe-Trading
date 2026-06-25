"""Adapter for optional TradingAgents integration."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

from src.research_analysis.models import ResearchAnalysisReport
from src.research_analysis.storage import DISCLAIMER, fallback_report


def _dotenv_values() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip().strip("'\"")
        if key.strip():
            values[key.strip()] = value
    return values


def _env(key: str, defaults: dict[str, str] | None = None) -> str:
    value = os.environ.get(key)
    if value:
        return value
    return (defaults or {}).get(key, "")


def _raw_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _first_text(data: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            return "\n".join(str(item) for item in value if str(item).strip())
    return ""


def _rating(value: Any, raw: str) -> str:
    text = f"{value or ''} {raw}".lower()
    if re.search(r"\b(strong\s+)?buy\b|看多|买入", text):
        return "buy"
    if re.search(r"\bsell\b|看空|卖出", text):
        return "sell"
    return "hold"


def _confidence(value: Any, raw: str) -> int:
    if isinstance(value, (int, float)):
        return max(0, min(100, int(value)))
    match = re.search(r"(confidence|置信度)[^\d]{0,12}(\d{1,3})", raw, flags=re.I)
    if match:
        return max(0, min(100, int(match.group(2))))
    return 60


def _risk_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()] or ["模型未给出明确风险项"]
    if isinstance(value, str) and value.strip():
        lines = [line.strip(" -•\t") for line in value.splitlines()]
        return [line for line in lines if line] or [value.strip()]
    return ["数据质量、市场波动和模型输出不确定性"]


def state_to_markdown(state: dict[str, Any], decision: Any) -> str:
    sections = [
        ("最终结论", state.get("final_trade_decision") or decision),
        ("市场/技术分析", state.get("market_report")),
        ("新闻分析", state.get("news_report")),
        ("情绪分析", state.get("sentiment_report")),
        ("基本面分析", state.get("fundamentals_report")),
        ("多空辩论", (state.get("investment_debate_state") or {}).get("history")),
        ("研究经理判断", state.get("investment_plan")),
        ("交易员计划", state.get("trader_investment_plan")),
        ("风险辩论", (state.get("risk_debate_state") or {}).get("history")),
        ("风控经理判断", (state.get("risk_debate_state") or {}).get("judge_decision")),
    ]
    chunks = ["# TradingAgents 原始分析报告"]
    for title, value in sections:
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, default=str)
        text = text.strip()
        if text:
            chunks.append(f"## {title}\n{text}")
    chunks.append(f"## 声明\n{DISCLAIMER}")
    return "\n\n".join(chunks).strip() + "\n"


def parse_decision(symbol: str, decision: Any) -> ResearchAnalysisReport:
    """Normalize TradingAgents output into the UI contract."""
    raw = _raw_text(decision)
    if not isinstance(decision, dict):
        return fallback_report(symbol, raw, structured=False)

    data = {str(key).lower(): value for key, value in decision.items()}
    rating = _rating(data.get("rating") or data.get("recommendation") or data.get("action"), raw)
    confidence = _confidence(data.get("confidence") or data.get("score"), raw)
    summary = _first_text(data, ["summary", "final_decision", "investment_plan", "decision", "rationale"])
    if not summary:
        return fallback_report(symbol, raw, structured=False)

    report = ResearchAnalysisReport(
        rating=rating,  # type: ignore[arg-type]
        confidence=confidence,
        horizon=_first_text(data, ["horizon", "time_horizon"]) or "中期",
        summary=summary[:1200],
        bull_case=_first_text(data, ["bull_case", "bullish", "bull_view"]) or "详见 TradingAgents 原始输出。",
        bear_case=_first_text(data, ["bear_case", "bearish", "bear_view"]) or "详见 TradingAgents 原始输出。",
        technical_view=_first_text(data, ["technical_view", "technical", "technical_analysis"]) or "详见 TradingAgents 原始输出。",
        fundamental_view=_first_text(data, ["fundamental_view", "fundamental", "fundamental_analysis"]) or "详见 TradingAgents 原始输出。",
        sentiment_news_view=_first_text(data, ["sentiment_news_view", "sentiment", "news", "news_analysis"]) or "详见 TradingAgents 原始输出。",
        risk_factors=_risk_list(data.get("risk_factors") or data.get("risks")),
        suggested_action=_first_text(data, ["suggested_action", "action", "recommendation"]) or "仅作为研究观点参考，不直接作为交易指令。",
        disclaimer=_first_text(data, ["disclaimer"]) or DISCLAIMER,
        structured=True,
    )
    return report


def _ensure_langgraph_runtime_compat() -> None:
    """Bridge LangGraph minor-version drift before importing TradingAgents."""
    try:
        import langgraph.runtime as runtime
    except Exception:
        return

    if not hasattr(runtime, "ExecutionInfo"):
        class ExecutionInfo(TypedDict, total=False):
            pass

        runtime.ExecutionInfo = ExecutionInfo  # type: ignore[attr-defined]
    if not hasattr(runtime, "ServerInfo"):
        class ServerInfo(TypedDict, total=False):
            pass

        runtime.ServerInfo = ServerInfo  # type: ignore[attr-defined]
    Runtime = getattr(runtime, "Runtime", None)
    if Runtime is not None:
        if not hasattr(Runtime, "execution_info"):
            Runtime.execution_info = None  # type: ignore[attr-defined]
        if not hasattr(Runtime, "server_info"):
            Runtime.server_info = None  # type: ignore[attr-defined]


_NODE_LABEL: dict[str, str] = {
    "Market Analyst": "📊 市场/技术分析中",
    "market_tools": "📊 获取市场数据中",
    "clear_market_messages": "📊 市场分析完成",
    "Sentiment Analyst": "💬 情绪分析中",
    "social_tools": "💬 获取社交媒体数据中",
    "clear_social_messages": "💬 情绪分析完成",
    "News Analyst": "📰 新闻分析中",
    "news_tools": "📰 获取新闻数据中",
    "clear_news_messages": "📰 新闻分析完成",
    "Fundamentals Analyst": "📋 基本面分析中",
    "fundamentals_tools": "📋 获取基本面数据中",
    "clear_fundamentals_messages": "📋 基本面分析完成",
    "Bull Researcher": "🐂 多方研究员辩论中",
    "Bear Researcher": "🐻 空方研究员辩论中",
    "Research Manager": "🎯 研究经理综合判断中",
    "Trader": "💹 交易员制定计划中",
    "Aggressive Analyst": "⚡ 激进风控分析师评估中",
    "Neutral Analyst": "⚖️ 中立风控分析师评估中",
    "Conservative Analyst": "🛡️ 保守风控分析师评估中",
    "Portfolio Manager": "📝 组合经理最终决策中",
}


def resolve_company_name(symbol: str) -> str | None:
    """Best-effort company name lookup via yfinance."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        return info.get("longName") or info.get("shortName") or None
    except Exception:
        return None


def run_tradingagents_analysis(
    symbol: str,
    analysis_date: str,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[ResearchAnalysisReport, Any, dict[str, Any], str]:
    """Run TradingAgents synchronously; callers should offload this to a worker thread."""
    env_values = _dotenv_values()
    supported_llm_keys = [
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_CN_API_KEY",
        "ZHIPU_API_KEY",
        "ZHIPU_CN_API_KEY",
        "MINIMAX_API_KEY",
        "MINIMAX_CN_API_KEY",
    ]
    if not any(_env(key, env_values) for key in supported_llm_keys):
        raise RuntimeError("TradingAgents 需要配置至少一个官方支持的 LLM API key，例如 OPENAI_API_KEY 或 OPENROUTER_API_KEY。")
    for key, value in env_values.items():
        if key and value and key not in os.environ:
            os.environ[key] = value

    try:
        _ensure_langgraph_runtime_compat()
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "TradingAgents 未安装。请在后端环境安装 TauricResearch/TradingAgents，并配置所需 API key 后重试。"
        ) from exc

    config = dict(DEFAULT_CONFIG)
    provider = _env("LANGCHAIN_PROVIDER", env_values).strip().lower()
    model_name = _env("LANGCHAIN_MODEL_NAME", env_values).strip()
    if provider:
        config["llm_provider"] = provider
    if model_name:
        config["quick_think_llm"] = model_name
        config["deep_think_llm"] = model_name
    if provider == "openrouter":
        config["backend_url"] = _env("OPENROUTER_BASE_URL", env_values).strip() or "https://openrouter.ai/api/v1"
    elif provider == "openai":
        config["backend_url"] = _env("OPENAI_BASE_URL", env_values).strip() or config.get("backend_url")
    config["output_language"] = "Chinese"

    if on_progress:
        on_progress("🔧 初始化 TradingAgents 引擎")

    graph = TradingAgentsGraph(debug=False, config=config)

    # Use streaming to report per-node progress
    graph.ticker = symbol
    graph._resolve_pending_entries(symbol)

    if graph.config.get("checkpoint_enabled"):
        from tradingagents.graph.checkpointing import get_checkpointer, checkpoint_step
        graph._checkpointer_ctx = get_checkpointer(graph.config["data_cache_dir"], symbol)
        saver = graph._checkpointer_ctx.__enter__()
        graph.graph = graph.workflow.compile(checkpointer=saver)

    try:
        past_context = graph.memory_log.get_past_context(symbol)
        instrument_context = graph.resolve_instrument_context(symbol)
        init_agent_state = graph.propagator.create_initial_state(
            symbol, analysis_date, asset_type="stock",
            past_context=past_context, instrument_context=instrument_context,
        )
        args = graph.propagator.get_graph_args()

        if graph.config.get("checkpoint_enabled"):
            from tradingagents.graph.checkpointing import thread_id
            tid = thread_id(symbol, str(analysis_date))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid

        final_state = {}
        seen_nodes: set[str] = set()
        for chunk in graph.graph.stream(init_agent_state, **args):
            final_state.update(chunk)
            for node_name in chunk:
                if node_name not in seen_nodes:
                    seen_nodes.add(node_name)
                    label = _NODE_LABEL.get(node_name)
                    if label and on_progress:
                        on_progress(label)

        graph.curr_state = final_state
        graph._log_state(analysis_date, final_state)
        graph.memory_log.store_decision(
            ticker=symbol,
            trade_date=analysis_date,
            final_trade_decision=final_state["final_trade_decision"],
        )
        if graph.config.get("checkpoint_enabled"):
            from tradingagents.graph.checkpointing import clear_checkpoint
            clear_checkpoint(graph.config["data_cache_dir"], symbol, str(analysis_date))

        decision = graph.process_signal(final_state["final_trade_decision"])
    finally:
        if graph._checkpointer_ctx is not None:
            graph._checkpointer_ctx.__exit__(None, None, None)
            graph._checkpointer_ctx = None
            graph.graph = graph.workflow.compile()

    if on_progress:
        on_progress("✅ 分析完成，正在生成报告")

    report_markdown = state_to_markdown(final_state, decision) if isinstance(final_state, dict) else _raw_text(final_state)
    raw_decision = {
        "decision": decision,
        "final_state": final_state,
    }
    return parse_decision(symbol, decision), raw_decision, {
        "engine": "TradingAgents",
        "debug": False,
        "llm_provider": config.get("llm_provider"),
        "quick_think_llm": config.get("quick_think_llm"),
        "deep_think_llm": config.get("deep_think_llm"),
        "analysis_date": analysis_date,
    }, report_markdown
