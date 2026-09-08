"""DeepSeek indicator summary: prompt construction and guardrails."""
from __future__ import annotations

import pytest

from src.forecast.indicator_ai import build_prompt, summarize_indicators


SNAP = {
    "price": 435.4,
    "macd": {"dif": -2.15, "dea": -1.02, "hist": -2.26, "prevHist": -1.8},
    "ma": {"ma50": 448.2, "ma200": 470.9},
    "rsi": 26.5,
    "boll": {"upper": 470.1, "mid": 450.0, "lower": 429.9, "pctB": 0.137, "bandwidthPct": 8.9},
    "atr": {"value": 9.7, "pctOfPrice": 2.23},
}


class FakeLLM:
    def __init__(self, reply="总体呈下行趋势。"):
        self.reply, self.messages = reply, None

    def chat(self, messages):
        self.messages = messages
        return self.reply


def test_prompt_carries_every_indicator():
    text = build_prompt("00700", "腾讯控股", "1Y", SNAP)
    for token in ("腾讯控股", "MACD", "DIF", "MA50", "MA200", "RSI(14)", "BOLL", "%B", "ATR(14)"):
        assert token in text


def test_prompt_says_atr_is_unavailable_rather_than_omitting_it():
    snap = {**SNAP}
    snap.pop("atr")
    assert "无法计算" in build_prompt("X", "X", "1Y", snap)


def test_prompt_renders_missing_numbers_as_a_dash():
    snap = {"price": 10.0, "macd": {"dif": None, "dea": None, "hist": None, "prevHist": None}}
    assert "—" in build_prompt("X", "X", "1Y", snap)


def test_system_prompt_forbids_advice_and_demands_conflict_disclosure():
    llm = FakeLLM()
    summarize_indicators(symbol="00700", name="腾讯控股", period="1Y", snapshot=SNAP, llm=llm)
    system = llm.messages[0]["content"]
    assert "严禁给出买卖建议" in system
    assert "矛盾" in system
    assert "不要臆造" in system


def test_returns_the_model_text():
    llm = FakeLLM("下行趋势,指标相互印证。")
    out = summarize_indicators(symbol="X", name="X", period="1Y", snapshot=SNAP, llm=llm)
    assert out == "下行趋势,指标相互印证。"


def test_rejects_a_snapshot_without_a_price():
    with pytest.raises(ValueError):
        summarize_indicators(symbol="X", name="X", period="1Y", snapshot={}, llm=FakeLLM())


def test_rejects_an_empty_model_reply():
    with pytest.raises(ValueError):
        summarize_indicators(symbol="X", name="X", period="1Y", snapshot=SNAP, llm=FakeLLM("   "))


class ResponseLike:
    """Mirrors ChatLLM's LLMResponse, which carries text on .content."""
    def __init__(self, content):
        self.content = content


class ObjectLLM:
    def __init__(self, content):
        self._content = content

    def chat(self, _messages):
        return ResponseLike(self._content)


def test_extracts_text_from_an_llm_response_object():
    out = summarize_indicators(
        symbol="X", name="X", period="1Y", snapshot=SNAP, llm=ObjectLLM("震荡下行。"),
    )
    assert out == "震荡下行。"


def test_rejects_a_response_object_with_empty_content():
    with pytest.raises(ValueError):
        summarize_indicators(
            symbol="X", name="X", period="1Y", snapshot=SNAP, llm=ObjectLLM(""),
        )
