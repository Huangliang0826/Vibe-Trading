"""个人成长:计划生成、进度推导与状态转换。"""
import json

import pytest

from src.growth.plan import (
    DOMAINS, MAX_TITLE, PLAN_DAYS, REQUEST_TIMEOUT_SECONDS, DomainIntake, Intake,
    build_prompt, fallback_plan, generate_domain_plan, parse_domain_plan,
)


def _steps(n=PLAN_DAYS, minutes=10):
    return [{"day": i, "title": f"动作{i}", "detail": "具体做法", "minutes": minutes}
            for i in range(1, n + 1)]


def _reply(**over):
    body = {
        "checkpoint": "录一段 1 分钟荷兰语,和第 1 天对比",
        "why": "先把开口跑顺",
        "min_version": "跟读 2 分钟",
        "steps": _steps(),
    }
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


class _FakeLLM:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self.text


# ── 输入校验 ──────────────────────────────────────────────────────────────────

def test_intake_rejects_a_level_that_is_not_one_of_the_offered_taps():
    # 全部输入都来自点选,所以任何自由值都说明请求被改过。
    with pytest.raises(ValueError, match="起点"):
        Intake(domains={"dutch": DomainIntake(level="fluent", minutes=10)},
               chronotype="early").validate()


def test_intake_rejects_minutes_outside_the_offered_choices():
    with pytest.raises(ValueError, match="分钟"):
        Intake(domains={"dutch": DomainIntake(level="zero", minutes=35)},
               chronotype="early").validate()


def test_prompt_states_the_users_own_time_budget_as_a_ceiling():
    prompt = build_prompt("dutch", DomainIntake(level="zero", minutes=20), "late")

    assert "20 分钟" in prompt and "40 分钟" in prompt  # 上限是预算的两倍
    assert "荷兰语" in prompt and "晚睡型" in prompt


# ── 解析 ──────────────────────────────────────────────────────────────────────

def test_parse_accepts_a_well_formed_plan():
    plan = parse_domain_plan(_reply(), minutes=10)

    assert len(plan["steps"]) == PLAN_DAYS
    assert [s["day"] for s in plan["steps"]] == list(range(1, PLAN_DAYS + 1))
    assert plan["source"] == "ai"


def test_parse_tolerates_a_markdown_fenced_reply():
    plan = parse_domain_plan(f"好的:\n```json\n{_reply()}\n```\n", minutes=10)

    assert len(plan["steps"]) == PLAN_DAYS


def test_parse_rejects_a_short_plan_rather_than_leaving_blank_days():
    with pytest.raises(ValueError, match="14"):
        parse_domain_plan(_reply(steps=_steps(9)), minutes=10)


def test_parse_rejects_a_plan_with_no_checkpoint():
    # 没有检查点,两周后就只有打卡数,没法说清进步在哪。
    with pytest.raises(ValueError, match="检查点"):
        parse_domain_plan(_reply(checkpoint=""), minutes=10)


def test_parse_clamps_minutes_into_the_users_budget():
    wild = _steps()
    wild[0]["minutes"] = 600
    wild[1]["minutes"] = 0

    plan = parse_domain_plan(_reply(steps=wild), minutes=10)

    assert plan["steps"][0]["minutes"] == 20  # 预算的两倍封顶
    assert plan["steps"][1]["minutes"] == 2   # 下限


def test_parse_clips_an_overlong_title():
    long = _steps()
    long[0]["title"] = "超" * 40

    plan = parse_domain_plan(_reply(steps=long), minutes=10)

    assert len(plan["steps"][0]["title"]) == MAX_TITLE


# ── 生成:失败必须退回兜底,而不是让功能不可用 ────────────────────────────────

def test_generate_falls_back_when_the_model_returns_garbage():
    plan = generate_domain_plan("dutch", DomainIntake(level="zero", minutes=10), "early",
                                llm=_FakeLLM("抱歉,我帮不了你"))

    assert plan["source"] == "fallback"
    assert len(plan["steps"]) == PLAN_DAYS


def test_generate_falls_back_when_the_model_raises():
    class Boom:
        def chat(self, messages, **kwargs):
            raise RuntimeError("provider down")

    plan = generate_domain_plan("dutch", DomainIntake(level="words", minutes=20), "early",
                                llm=Boom())

    assert plan["source"] == "fallback"


def test_generate_uses_the_model_when_it_answers_properly():
    llm = _FakeLLM(_reply())

    plan = generate_domain_plan("dutch", DomainIntake(level="zero", minutes=10), "early", llm=llm)

    assert plan["source"] == "ai"
    assert len(llm.calls) == 1


def test_every_planned_domain_has_a_usable_fallback():
    for domain in DOMAINS:
        plan = fallback_plan(domain, 10)
        assert len(plan["steps"]) == PLAN_DAYS
        assert plan["checkpoint"] and plan["min_version"]


def test_fallback_second_week_asks_for_more_than_the_first():
    plan = fallback_plan("dutch", 20)

    assert plan["steps"][7]["minutes"] > plan["steps"][0]["minutes"]


def test_the_model_call_carries_a_timeout():
    # 没有超时,provider 一旦挂起就把整个请求拖住——实测卡过几分钟。
    seen: dict = {}

    class Recorder:
        def chat(self, messages, **kwargs):
            seen.update(kwargs)
            return _reply()

    generate_domain_plan("dutch", DomainIntake(level="zero", minutes=10), "early", llm=Recorder())

    assert seen["timeout"] == REQUEST_TIMEOUT_SECONDS
