"""英语句型的间隔重复练习——全是纯函数。

目标是"调用自动化":交流时不经过翻译就能脱口而出。能做到这件事的练法只有
**检索练习**——先看中文情境、自己产出英文,再对答案。只看英文觉得"认识"是
识别,识别和产出之间隔着整整一层,而卡壳正发生在产出那一层。

因此评分不是"对/错",而是**取回这句话花了多久**:

* ``again``   想不起来     → 退回第 0 盒,当场再排一次
* ``slow``    想起来了但卡 → 留在原盒,按原间隔再见
* ``instant`` 脱口而出     → 进下一盒

只有连续"脱口而出"才能走到最后一盒。这正是自动化的定义:不是答得对,是
答得不用想。
"""

from __future__ import annotations

from datetime import date, timedelta

from src.growth.english_patterns import PATTERN_BY_ID, PATTERNS, TOTAL

GRADES = ("again", "slow", "instant")

#: 第 0~4 盒的复习间隔(天)。最后一盒 21 天仍能脱口而出,才算真的固化。
INTERVALS = (1, 2, 4, 9, 21)
MAX_BOX = len(INTERVALS) - 1

#: 每天最多引入几个新句型。一次灌太多,第二天的复习量会直接劝退。
NEW_PER_DAY = 8
#: 单次练习的条目上限。十几条、几分钟能做完,才可能每天都做。
SESSION_LIMIT = 20


def _add_days(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def new_reviews() -> dict:
    return {}


def apply_review(reviews: dict, pattern_id: str, grade: str, today: str) -> dict:
    """记一次评分,返回新的复习表。"""
    if pattern_id not in PATTERN_BY_ID:
        raise ValueError(f"没有这个句型:{pattern_id}")
    if grade not in GRADES:
        raise ValueError(f"评分只能是 {GRADES} 之一:{grade}")

    entry = dict(reviews.get(pattern_id) or {})
    box = int(entry.get("box", 0))

    if grade == "again":
        box = 0
        due = today  # 当场再排一次,别等到明天
    elif grade == "slow":
        due = _add_days(today, INTERVALS[box])
    else:
        box = min(box + 1, MAX_BOX)
        due = _add_days(today, INTERVALS[box])

    return {
        **reviews,
        pattern_id: {
            "box": box,
            "due": due,
            "seen": int(entry.get("seen", 0)) + 1,
            "first": entry.get("first") or today,
            "last": today,
            # 记录最后一次的手感,用于"还卡壳的句型"清单。
            "last_grade": grade,
        },
    }


def introduced_today(reviews: dict, today: str) -> int:
    return sum(1 for e in reviews.values() if e.get("first") == today)


def build_session(reviews: dict, today: str, *, new_per_day: int = NEW_PER_DAY,
                  limit: int = SESSION_LIMIT) -> list[dict]:
    """今天要练的条目:先清到期的,再按余额补新的。

    到期的永远优先于新的——积压的复习才是记忆真正流失的地方,新鲜感不该
    排在它前面。
    """
    due = [
        (entry, PATTERN_BY_ID[pid])
        for pid, entry in reviews.items()
        if pid in PATTERN_BY_ID and str(entry.get("due", "")) <= today
    ]
    due.sort(key=lambda pair: (str(pair[0].get("due", "")), int(pair[0].get("box", 0))))

    items = [
        {**pattern.to_dict(), "status": "review", "box": int(entry.get("box", 0)),
         "seen": int(entry.get("seen", 0))}
        for entry, pattern in due[:limit]
    ]

    budget = max(0, new_per_day - introduced_today(reviews, today))
    room = max(0, limit - len(items))
    if budget and room:
        fresh = [p for p in PATTERNS if p.id not in reviews]
        items += [
            {**p.to_dict(), "status": "new", "box": 0, "seen": 0}
            for p in fresh[: min(budget, room)]
        ]
    return items


def stats(reviews: dict, today: str) -> dict:
    """进度总览。``automatic`` 是真正要追的那个数字。"""
    boxes = [int(e.get("box", 0)) for e in reviews.values()]
    return {
        "total": TOTAL,
        "started": len(reviews),
        "automatic": sum(1 for b in boxes if b >= MAX_BOX),
        "due_today": sum(1 for e in reviews.values() if str(e.get("due", "")) <= today),
        "reviewed_today": sum(1 for e in reviews.values() if e.get("last") == today),
        "box_counts": {str(b): boxes.count(b) for b in range(len(INTERVALS))},
    }


def shaky(reviews: dict, limit: int = 8) -> list[dict]:
    """练过但还卡壳的句型——复习得最多却仍在低盒的那些。"""
    rows = [
        (PATTERN_BY_ID[pid], entry)
        for pid, entry in reviews.items()
        if pid in PATTERN_BY_ID and int(entry.get("seen", 0)) >= 3
        and int(entry.get("box", 0)) <= 1
    ]
    rows.sort(key=lambda pair: -int(pair[1].get("seen", 0)))
    return [
        {"id": p.id, "frame": p.frame, "meaning": p.meaning, "seen": int(e.get("seen", 0))}
        for p, e in rows[:limit]
    ]
