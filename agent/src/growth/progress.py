"""个人成长:进度推导——全是纯函数,方便测试也方便信任。

两个判断贯穿整个模块:

* **今天该做哪一步,取决于做到了第几步,而不是日历第几天。** 漏了一天,内容
  不会被跳过,只是整体往后挪。错过一天就永远少学一天,是让人放弃的最快方式。
* **进步必须能被指出来,而不是只有打卡数。** 所以每个领域都带一个检查点,
  第 1 天记一次基线,第 14 天再记一次,界面上直接把两个数摆在一起。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from src.growth.plan import DOMAIN_LABELS, PLAN_DAYS


def ymd(value: date) -> str:
    return value.isoformat()


def parse_ymd(value: str) -> date:
    return date.fromisoformat(value)


def add_days(value: str, days: int) -> str:
    return ymd(parse_ymd(value) + timedelta(days=days))


def days_between(start: str, end: str) -> int:
    return (parse_ymd(end) - parse_ymd(start)).days


@dataclass
class DomainProgress:
    domain: str
    label: str
    done: int
    total: int
    #: 下一个未完成的步骤;全部做完时为 None。
    next_step: Optional[dict]
    #: 今天是否已经打过卡——决定界面显示"去做"还是"已完成"。
    done_today: bool
    #: 今天已完成的那一步。打完卡后界面要显示"刚做完的是什么",而不是明天的
    #: 内容——否则"今天完成"会贴在一个还没做的动作上。
    today_step: Optional[dict] = None
    #: 今天记录的感受 1~3,没记为 None。派生到这里,免得把原始打卡日志发给前端。
    feeling_today: Optional[int] = None
    #: 14 个格子的状态,done/next/todo,用于一眼看完整体。
    dots: list[str] = field(default_factory=list)
    checkpoint: str = ""
    min_version: str = ""
    why: str = ""

    @property
    def percent(self) -> int:
        return round(self.done / self.total * 100) if self.total else 0

    def to_dict(self) -> dict:
        return {
            "domain": self.domain, "label": self.label,
            "done": self.done, "total": self.total, "percent": self.percent,
            "next_step": self.next_step, "today_step": self.today_step,
            "done_today": self.done_today,
            "feeling_today": self.feeling_today,
            "dots": self.dots, "checkpoint": self.checkpoint,
            "min_version": self.min_version, "why": self.why,
        }


def domain_progress(domain: str, plan: dict, checkins: list[dict], today: str) -> DomainProgress:
    """按"做到第几步"推进,而不是按日历日推进。"""
    steps = plan.get("steps") or []
    mine = [c for c in checkins if c.get("domain") == domain]
    today_entry = next((c for c in mine if c.get("date") == today), None)
    done = min(len(mine), len(steps))
    next_step = steps[done] if done < len(steps) else None
    # 今天打过卡时,最后完成的那一步就是今天做的。
    today_step = steps[done - 1] if today_entry is not None and done else None
    dots = ["done"] * done
    if next_step is not None:
        dots.append("next")
        dots += ["todo"] * (len(steps) - done - 1)

    return DomainProgress(
        domain=domain,
        label=DOMAIN_LABELS.get(domain, domain),
        done=done,
        total=len(steps),
        next_step=next_step,
        today_step=today_step,
        done_today=today_entry is not None,
        feeling_today=today_entry.get("feeling") if today_entry else None,
        dots=dots,
        checkpoint=plan.get("checkpoint", ""),
        min_version=plan.get("min_version", ""),
        why=plan.get("why", ""),
    )


def streak(checkins: list[dict], today: str) -> int:
    """连续打卡天数。

    今天还没打卡时,仍然按截至昨天计算——早上打开应用就看到 0,是在为还没
    发生的事惩罚人。
    """
    dates = {c.get("date") for c in checkins if c.get("date")}
    if not dates:
        return 0
    cursor = today if today in dates else add_days(today, -1)
    count = 0
    while cursor in dates:
        count += 1
        cursor = add_days(cursor, -1)
    return count


def missed_two_days(checkins: list[dict], today: str) -> bool:
    """只有连续断两天才提醒——断一天是常态,不值得被追着说。

    今天已经打过卡就不提醒:没有缺口可说。从来没打过卡也不提醒,否则刚建完
    计划的第一天就被数落一句"断了两天"。
    """
    dates = {c.get("date") for c in checkins if c.get("date")}
    if not dates or today in dates:
        return False
    return add_days(today, -1) not in dates and add_days(today, -2) not in dates


def checkpoint_status(state: dict, today: str) -> dict:
    """两周检查点:什么时候测、测过没有。"""
    start = state.get("start_date") or today
    elapsed = days_between(start, today)
    due_date = add_days(start, PLAN_DAYS - 1)
    marks = state.get("checkpoints") or {}
    return {
        "start_date": start,
        "due_date": due_date,
        "elapsed_days": elapsed,
        "days_left": max(0, days_between(today, due_date)),
        "due": elapsed >= PLAN_DAYS - 1,
        "baselines": {d: (marks.get(d) or {}).get("start", "") for d in marks},
        "results": {d: (marks.get(d) or {}).get("end", "") for d in marks},
    }


def build_overview(state: dict, today: str) -> dict:
    """界面需要的全部派生数据,一次算完。"""
    plan = state.get("plan") or {}
    checkins = state.get("checkins") or []
    domains = [domain_progress(d, plan[d], checkins, today) for d in plan]
    total_steps = sum(d.total for d in domains)
    total_done = sum(d.done for d in domains)

    return {
        "today": today,
        "streak": streak(checkins, today),
        "nudge": missed_two_days(checkins, today),
        "domains": [d.to_dict() for d in domains],
        "done_today": sum(1 for d in domains if d.done_today),
        "domain_count": len(domains),
        "total_done": total_done,
        "total_steps": total_steps,
        "percent": round(total_done / total_steps * 100) if total_steps else 0,
        "checkpoint": checkpoint_status(state, today),
    }
