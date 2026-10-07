"""打卡日历与累计成果——全是纯函数。

一天只要有一门语言达成了当天目标就算打了卡;两门都达成的那天标成实心。
把"做了一半"也画出来,比只认全勤诚实,也更不容易让人因为断一次就放弃。
"""

from __future__ import annotations

from datetime import date, timedelta

#: 日历回看多少天。四周刚好铺满一屏,也够看出节奏。
CALENDAR_DAYS = 28


def ymd(value: date) -> str:
    return value.isoformat()


def parse_ymd(value: str) -> date:
    return date.fromisoformat(value)


def add_days(value: str, days: int) -> str:
    return ymd(parse_ymd(value) + timedelta(days=days))


def build_calendar(days_by_lang: dict[str, set[str]], today: str,
                   days: int = CALENDAR_DAYS) -> list[dict]:
    """最近 ``days`` 天的打卡情况,从早到晚。"""
    langs = sorted(days_by_lang)
    out = []
    for offset in range(days - 1, -1, -1):
        day = add_days(today, -offset)
        done = {lang: day in days_by_lang[lang] for lang in langs}
        hit = sum(done.values())
        out.append({
            "date": day,
            "langs": done,
            "state": "full" if hit == len(langs) and hit else "partial" if hit else "none",
        })
    return out


def build_summary(days_by_lang: dict[str, set[str]], today: str) -> dict:
    """累计成果。``streak`` 用的是宽容规则:今天还没练也先按截至昨天算。"""
    sets = list(days_by_lang.values()) or [set()]
    active: set[str] = set().union(*sets)
    full = set.intersection(*sets) if sets and all(sets) else set()
    if not active:
        return {"active_days": 0, "full_days": 0, "streak": 0, "best_streak": 0}

    cursor = today if today in active else add_days(today, -1)
    streak = 0
    while cursor in active:
        streak += 1
        cursor = add_days(cursor, -1)

    best = run = 0
    previous = None
    for day in sorted(active):
        run = run + 1 if previous and add_days(previous, 1) == day else 1
        best = max(best, run)
        previous = day

    return {
        "active_days": len(active),
        "full_days": len(full),
        "streak": streak,
        "best_streak": best,
    }
