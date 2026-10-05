"""个人成长:四个领域的两周计划——意图、生成与校验。

设计出发点是用户的一句话:"我不想自己去设置复杂的计划"。所以这里只收集
**点选**得到的最少信息(每个领域的起点 + 每天愿意给的分钟数,外加一个作息
类型),由模型把它展开成 14 天可直接执行的动作。

两个硬性约束:

* 计划必须可执行到"不用再想"——每一步都有具体动作和分钟数,外加一个 2 分钟
  的兜底版本,状态差的日子也不至于断掉。
* 计划必须可检验——每个领域都带一个两周后能真的测一次的检查点,否则"看到
  进步"只是感觉。

模型不可用或返回不合格时,``fallback_plan`` 给出一份保守的确定性计划:功能
可用性不依赖外部服务。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

MODEL_NAME = "deepseek/deepseek-v4-flash"
PLAN_VERSION = "growth-plan-v1"
PLAN_DAYS = 14

#: 单个领域的模型调用上限。没有上限时,provider 一旦挂起就把整个请求拖住——
#: 实测中正是这样卡了几分钟。超时按失败处理,退回兜底计划。
REQUEST_TIMEOUT_SECONDS = 60

DOMAINS = ("sleep", "fitness", "dutch", "english")
DOMAIN_LABELS = {"sleep": "睡眠", "fitness": "健身", "dutch": "荷兰语", "english": "英语"}

#: 每个领域的起点选项(点选,不填空)。
LEVELS: dict[str, tuple[tuple[str, str], ...]] = {
    "sleep": (("hard_to_sleep", "入睡困难"), ("too_short", "睡得着但不够"), ("irregular", "作息不规律")),
    "fitness": (("sedentary", "几乎不动"), ("occasional", "偶尔运动"), ("regular", "有规律想提升")),
    "dutch": (("zero", "零基础"), ("words", "认得一些词"), ("basic_talk", "能简单对话")),
    "english": (("read_only", "能读不敢说"), ("daily_ok", "日常够用"), ("to_pro", "想到专业水平")),
}

#: 每天愿意投入的分钟数(点选)。
MINUTE_CHOICES = (10, 20, 40)

CHRONOTYPES = (("early", "早起型"), ("late", "晚睡型"), ("irregular", "不规律"))

MAX_TITLE = 18
MAX_DETAIL = 48


@dataclass(frozen=True)
class DomainIntake:
    """一个领域的全部输入——两次点选。"""

    level: str
    minutes: int

    def validate(self, domain: str) -> None:
        if self.level not in {key for key, _ in LEVELS[domain]}:
            raise ValueError(f"{domain} 的起点取值不合法:{self.level}")
        if self.minutes not in MINUTE_CHOICES:
            raise ValueError(f"{domain} 的每日分钟数不合法:{self.minutes}")


@dataclass(frozen=True)
class Intake:
    """生成计划所需的全部信息。没有自由文本必填项。"""

    domains: dict[str, DomainIntake]
    chronotype: str

    def validate(self) -> None:
        if not self.domains:
            raise ValueError("至少要选一个领域")
        for domain, item in self.domains.items():
            if domain not in DOMAINS:
                raise ValueError(f"未知领域:{domain}")
            item.validate(domain)
        if self.chronotype not in {key for key, _ in CHRONOTYPES}:
            raise ValueError(f"作息类型不合法:{self.chronotype}")


def level_label(domain: str, level: str) -> str:
    return dict(LEVELS[domain]).get(level, level)


def chronotype_label(key: str) -> str:
    return dict(CHRONOTYPES).get(key, key)


# ── 提示词 ────────────────────────────────────────────────────────────────────

#: 安全边界写进系统提示而不是事后过滤:健身和睡眠都挨着医疗建议,模型越界
#: 一次就可能让人受伤,所以直接禁止,并要求保守递进。
_SYSTEM = (
    "你是务实的习惯教练,为用户制定两周(14 天)的可执行计划。\n"
    "硬性要求:\n"
    "1. 每一天给一个**具体到不用再想**的动作,而不是'练听力''加强锻炼'这类口号。\n"
    "2. 难度必须保守递进:第 1 天要容易到几乎不可能失败,两周内缓慢加量。\n"
    "3. 禁止任何医疗、用药、补剂建议;健身只用自重或轻器械,并假设用户没有教练。\n"
    "4. 不要编造具体网址、App 内不存在的课程编号或书的页码。\n"
    "5. 检查点必须是两周后能真的测一次的事,要有数字或可录音/可计数的证据。\n"
    "6. 全部用简体中文。\n"
    "只输出 JSON,不要 Markdown 代码块,结构为:\n"
    '{"checkpoint": "两周后怎么测,一句话", "why": "为什么这样安排,一句话", '
    '"min_version": "状态差时的 2 分钟兜底动作", '
    f'"steps": [{{"day": 1, "title": "≤{MAX_TITLE}字的动作名", '
    f'"detail": "≤{MAX_DETAIL}字的具体做法", "minutes": 10}}, ...共 {PLAN_DAYS} 天]}}'
)


def build_prompt(domain: str, intake: DomainIntake, chronotype: str) -> str:
    """把点选结果渲染成用户轮。"""
    return (
        f"领域:{DOMAIN_LABELS[domain]}\n"
        f"我的起点:{level_label(domain, intake.level)}\n"
        f"每天能给:{intake.minutes} 分钟\n"
        f"作息:{chronotype_label(chronotype)}\n"
        f"请给出 {PLAN_DAYS} 天的计划。每天的 minutes 应当在 {intake.minutes} 分钟上下,"
        f"不要超过 {intake.minutes * 2} 分钟。"
    )


# ── 解析与校验 ────────────────────────────────────────────────────────────────

def _clip(text: Any, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s[:limit]


def _extract_json(text: str) -> dict:
    """容忍模型裹上代码块或前后多余文字。"""
    cleaned = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("模型返回里没有 JSON 对象")
        return json.loads(cleaned[start : end + 1])


def parse_domain_plan(raw: str, *, minutes: int) -> dict:
    """把模型输出解析成一个领域的计划,不合格就抛错。

    严格要求 14 天齐备且日号为 1..14:缺一天在界面上就是一个空白格子,
    与其显示半份计划,不如退回确定性兜底版本。
    """
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("计划必须是 JSON 对象")

    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list) or len(steps_raw) != PLAN_DAYS:
        raise ValueError(f"steps 必须正好 {PLAN_DAYS} 条,实际 {len(steps_raw) if isinstance(steps_raw, list) else '非列表'}")

    steps: list[dict] = []
    for index, item in enumerate(steps_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 天不是对象")
        title = _clip(item.get("title"), MAX_TITLE)
        if not title:
            raise ValueError(f"第 {index} 天缺少动作名")
        try:
            step_minutes = int(float(item.get("minutes", minutes)))
        except (TypeError, ValueError):
            step_minutes = minutes
        # 模型偶尔会给出 0 或离谱的大数;收敛到用户愿意投入的区间内。
        step_minutes = max(2, min(step_minutes, minutes * 2))
        steps.append({
            "day": index,
            "title": title,
            "detail": _clip(item.get("detail"), MAX_DETAIL),
            "minutes": step_minutes,
        })

    checkpoint = _clip(data.get("checkpoint"), 80)
    if not checkpoint:
        raise ValueError("缺少检查点:没有它两周后无法验证进步")
    min_version = _clip(data.get("min_version"), 40)
    if not min_version:
        raise ValueError("缺少 2 分钟兜底动作")

    return {
        "checkpoint": checkpoint,
        "why": _clip(data.get("why"), 60),
        "min_version": min_version,
        "steps": steps,
        "source": "ai",
    }


# ── 兜底计划 ──────────────────────────────────────────────────────────────────

#: 模型不可用时用的确定性计划。刻意朴素:第二周只是把第一周的动作加量,
#: 保证"能用",真正的好计划由模型给。
_FALLBACK: dict[str, dict[str, str]] = {
    "sleep": {
        "checkpoint": "对比第 1 天和第 14 天记录的入睡时间,看平均是否提前 20 分钟",
        "why": "先把起床时间钉死,节律稳了睡眠时长才跟得上",
        "min_version": "睡前把手机放到床以外的地方充电",
        "title_w1": "固定起床 + 睡前无屏",
        "detail_w1": "每天同一时间起床;睡前这段时间不看手机,记下入睡时间",
        "title_w2": "延长无屏时段",
        "detail_w2": "起床时间不变,把睡前无屏时段再往前推,继续记录入睡时间",
    },
    "fitness": {
        "checkpoint": "测一次连续深蹲和靠墙静蹲秒数,和第 1 天的数字比",
        "why": "自重动作先建立频率,次数的提升两周内看得见",
        "min_version": "做 5 个深蹲",
        "title_w1": "自重三件套",
        "detail_w1": "深蹲、俯卧撑(可跪姿)、靠墙静蹲各一组,留有余力就停",
        "title_w2": "自重三件套加量",
        "detail_w2": "同样三个动作,每组比第一周多几次;任何疼痛立刻停",
    },
    "dutch": {
        "checkpoint": "录一段 1 分钟荷兰语自我介绍,和第 1 天的录音对比",
        "why": "先把发音和高频词跑顺,开口比记单词更快见效",
        "min_version": "跟读 2 分钟荷兰语音频",
        "title_w1": "跟读 + 高频词",
        "detail_w1": "跟读一段慢速荷兰语音频,挑 5 个高频词出声念熟",
        "title_w2": "跟读 + 复述",
        "detail_w2": "同样跟读,然后不看文本复述大意,录下来",
    },
    "english": {
        "checkpoint": "录一段 2 分钟英语口头表达,和第 1 天的录音对比流利度",
        "why": "能读不敢说的瓶颈在产出,所以把时间压在开口上",
        "min_version": "用英语说 2 分钟今天做了什么",
        "title_w1": "口头输出",
        "detail_w1": "就一个话题不停嘴地说完,卡住也不要停,录音",
        "title_w2": "口头输出 + 回听",
        "detail_w2": "同样说完录音,回听一遍挑出 3 个想改的表达",
    },
}


def fallback_plan(domain: str, minutes: int) -> dict:
    """确定性计划:模型失败时仍然给出完整的 14 天。"""
    spec = _FALLBACK[domain]
    steps = []
    for day in range(1, PLAN_DAYS + 1):
        second_week = day > 7
        steps.append({
            "day": day,
            "title": spec["title_w2"] if second_week else spec["title_w1"],
            "detail": spec["detail_w2"] if second_week else spec["detail_w1"],
            "minutes": round(minutes * 1.25) if second_week else minutes,
        })
    return {
        "checkpoint": spec["checkpoint"],
        "why": spec["why"],
        "min_version": spec["min_version"],
        "steps": steps,
        "source": "fallback",
    }


def generate_domain_plan(
    domain: str, intake: DomainIntake, chronotype: str, *, llm: Optional[Any] = None,
) -> dict:
    """生成一个领域的计划;模型出问题时退回兜底计划而不是报错。

    逐领域单独调用,这样一个领域失败不会把整份计划拖垮。
    """
    intake.validate(domain)
    if llm is None:
        from src.providers.chat import ChatLLM
        llm = ChatLLM(model_name=MODEL_NAME)

    try:
        reply = llm.chat(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": build_prompt(domain, intake, chronotype)},
            ],
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        text = reply if isinstance(reply, str) else str(getattr(reply, "content", "") or "")
        return parse_domain_plan(text, minutes=intake.minutes)
    except Exception as exc:  # noqa: BLE001 - 任何失败都退回兜底,功能不能因此不可用
        logger.warning("growth: %s 领域计划生成失败,使用兜底计划:%s", domain, exc)
        return fallback_plan(domain, intake.minutes)
