"""DeepSeek summary of the chart's technical indicators.

Takes the indicator values the chart already computed (so the narrative and the
AI describe the same numbers) and asks the model to synthesise them into one
trend read.

Two guardrails matter here:

* The model is given only the indicator values — never asked to fetch or invent
  prices — and is instructed to say so when the indicators disagree rather than
  manufacture a confident story.
* The project's edge scorecard has not established predictive power for these
  indicators, so the prompt forbids price targets and buy/sell calls.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

MODEL_NAME = "deepseek/deepseek-v4-flash"
ANALYSIS_VERSION = "indicator-ai-v1"

_SYSTEM = (
    "你是严谨的技术分析助手。用户会给你一只标的的技术指标数值,"
    "请只依据这些数值做归纳,不要臆造价格、成交量或新闻。\n"
    "要求:\n"
    "1. 先用一句话给出总体趋势判断(上行/下行/震荡),并说明主要依据。\n"
    "2. 指出各指标之间是相互印证还是彼此矛盾——矛盾时必须明说,不要强行编出一致结论。\n"
    "3. 用 ATR 说明当前波动水平对应的合理止损距离量级。\n"
    "4. 严禁给出买卖建议、目标价或涨跌幅预测。\n"
    "5. 用简体中文,120 字以内,不使用 Markdown 标题。"
)


def _fmt(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def build_prompt(symbol: str, name: str, period: str, snapshot: dict) -> str:
    """Render the indicator snapshot as the user turn."""
    lines = [f"标的:{name}({symbol}) · 区间:{period}", f"最新价:{_fmt(snapshot.get('price'))}"]

    macd = snapshot.get("macd") or {}
    if macd:
        lines.append(
            f"MACD:DIF {_fmt(macd.get('dif'), 4)} / DEA {_fmt(macd.get('dea'), 4)} / "
            f"柱 {_fmt(macd.get('hist'), 4)}(前值 {_fmt(macd.get('prevHist'), 4)})"
        )
    ma = snapshot.get("ma") or {}
    if ma:
        lines.append(f"均线:MA50 {_fmt(ma.get('ma50'))} / MA200 {_fmt(ma.get('ma200'))}")
    if snapshot.get("rsi") is not None:
        lines.append(f"RSI(14):{_fmt(snapshot.get('rsi'), 1)}")
    boll = snapshot.get("boll") or {}
    if boll:
        lines.append(
            f"BOLL(20,2):上轨 {_fmt(boll.get('upper'))} / 中轨 {_fmt(boll.get('mid'))} / "
            f"下轨 {_fmt(boll.get('lower'))},%B {_fmt(boll.get('pctB'), 2)},"
            f"带宽 {_fmt(boll.get('bandwidthPct'), 1)}%"
        )
    atr = snapshot.get("atr") or {}
    if atr:
        lines.append(f"ATR(14):{_fmt(atr.get('value'))}(约为现价 {_fmt(atr.get('pctOfPrice'), 2)}%)")
    else:
        lines.append("ATR(14):数据缺少高低价,无法计算")
    return "\n".join(lines)


def summarize_indicators(
    *, symbol: str, name: str, period: str, snapshot: dict, llm: Optional[Any] = None,
) -> str:
    """Return a short Chinese trend read, or raise on an unusable response."""
    if not isinstance(snapshot, dict) or snapshot.get("price") is None:
        raise ValueError("snapshot must include at least a price")

    if llm is None:
        from src.providers.chat import ChatLLM
        llm = ChatLLM(model_name=MODEL_NAME)

    reply = llm.chat([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": build_prompt(symbol, name, period, snapshot)},
    ])
    # ChatLLM returns an LLMResponse; a plain string is allowed for test fakes.
    text = (reply if isinstance(reply, str) else str(getattr(reply, "content", "") or "")).strip()
    if not text:
        raise ValueError("empty response from model")
    return text
