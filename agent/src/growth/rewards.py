"""等级与成就——全是纯函数,全部由已有的练习数据推导。

**不自己造一套积分。** 奖励如果和真实水平脱钩,就只是在奖励点击次数:点得越
多分越高,人很快会发现这件事,然后它就彻底失去意义了。

所以等级只看一个东西:**走到最后一盒的条数**。要进最后一盒,必须在 21 天的
间隔之后仍然"脱口而出"(六秒内答对),答错一次就退回第一盒。这个数字涨得慢,
但它涨的时候,是真的记住了。

成就同理,每一条都对应一件确实做到的事,而不是"打开应用三次"。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.growth.practice import MAX_BOX

#: 等级门槛:达到这个掌握数就进入该级。刻意前松后紧——开头要让人看见动静,
#: 后面要让"又升一级"保持分量。
LEVELS: tuple[tuple[int, str], ...] = (
    (0, "起步"),
    (10, "上手"),
    (30, "成形"),
    (75, "扎实"),
    (150, "自如"),
    (300, "精通"),
)


def mastered_count(reviews: dict) -> int:
    """走到最后一盒的条数。"""
    return sum(1 for e in reviews.values() if int(e.get("box", 0)) >= MAX_BOX)


def level_of(mastered: int) -> dict:
    """当前等级,以及到下一级还差多少。"""
    index = 0
    for i, (threshold, _) in enumerate(LEVELS):
        if mastered >= threshold:
            index = i
    _, label = LEVELS[index]
    floor = LEVELS[index][0]
    nxt = LEVELS[index + 1] if index + 1 < len(LEVELS) else None
    span = (nxt[0] - floor) if nxt else 0
    return {
        "level": index + 1,
        "label": label,
        "mastered": mastered,
        "next_at": nxt[0] if nxt else None,
        "next_label": nxt[1] if nxt else None,
        "to_next": max(0, nxt[0] - mastered) if nxt else 0,
        # 本级进度 0~100;满级时固定 100。
        "percent": 100 if not nxt else round((mastered - floor) / max(1, span) * 100),
    }


@dataclass(frozen=True)
class Achievement:
    key: str
    label: str
    detail: str
    #: 达成所需的数量;到达即解锁。
    target: int
    icon: str


ACHIEVEMENTS: tuple[Achievement, ...] = (
    Achievement("first_quiz", "开口第一次", "完成第一次测验", 1, "sparkles"),
    Achievement("streak_7", "一周不断", "连续 7 天练习", 7, "flame"),
    Achievement("streak_14", "两周不断", "连续 14 天练习", 14, "flame"),
    Achievement("streak_30", "一月不断", "连续 30 天练习", 30, "flame"),
    Achievement("studied_100", "见过一百句", "学习页看过 100 条", 100, "book"),
    Achievement("studied_300", "见过三百句", "学习页看过 300 条", 300, "book"),
    Achievement("mastered_10", "十句入脑", "10 条推到最后一盒", 10, "brain"),
    Achievement("mastered_50", "五十句入脑", "50 条推到最后一盒", 50, "brain"),
    Achievement("mastered_150", "百五十句入脑", "150 条推到最后一盒", 150, "brain"),
    Achievement("correct_500", "答对五百题", "累计答对 500 题", 500, "target"),
    Achievement("comeback_10", "错过才记牢", "10 条曾经答错、最终推到最后一盒", 10, "undo"),
    Achievement("bilingual_day", "一天两门", "同一天两门语言都达标", 1, "languages"),
    Achievement("favorites_20", "收藏二十句", "收藏 20 条", 20, "bookmark"),
    Achievement("dutch_50", "荷语起步", "荷兰语练过 50 条", 50, "flag"),
)


def _best_streak(days: set[str]) -> int:
    if not days:
        return 0
    best = run = 0
    previous: date | None = None
    for day in sorted(date.fromisoformat(d) for d in days):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        best = max(best, run)
        previous = day
    return best


def progress(docs: dict[str, dict], goal_days_by_lang: dict[str, set[str]]) -> dict[str, int]:
    """每项成就当前的进度数。``docs`` 是各语言的完整文档。"""
    all_reviews = {k: v for doc in docs.values() for k, v in (doc.get("reviews") or {}).items()}
    answered = sum(int(row.get("answered", 0))
                   for doc in docs.values() for row in (doc.get("daily") or {}).values())
    correct = sum(int(row.get("correct", 0))
                  for doc in docs.values() for row in (doc.get("daily") or {}).values())
    active = set().union(*goal_days_by_lang.values()) if goal_days_by_lang else set()
    both = set.intersection(*goal_days_by_lang.values()) if goal_days_by_lang else set()
    streak = _best_streak(active)
    mastered = mastered_count(all_reviews)
    dutch_reviews = (docs.get("nl") or {}).get("reviews") or {}

    return {
        "first_quiz": 1 if answered else 0,
        "streak_7": streak,
        "streak_14": streak,
        "streak_30": streak,
        "studied_100": sum(1 for e in all_reviews.values() if e.get("studied")),
        "studied_300": sum(1 for e in all_reviews.values() if e.get("studied")),
        "mastered_10": mastered,
        "mastered_50": mastered,
        "mastered_150": mastered,
        "correct_500": correct,
        # 曾经答错、最后仍然推到最后一盒的条数。这是最值得标出来的一类进步:
        # 一次就会的不算本事,错过又记牢了才算。
        "comeback_10": sum(1 for e in all_reviews.values()
                           if int(e.get("wrong", 0)) > 0 and int(e.get("box", 0)) >= MAX_BOX),
        "bilingual_day": len(both),
        "favorites_20": sum(1 for e in all_reviews.values() if e.get("favorite")),
        "dutch_50": sum(1 for e in dutch_reviews.values() if e.get("studied")),
    }


def build_rewards(docs: dict[str, dict], goal_days_by_lang: dict[str, set[str]]) -> dict:
    """等级 + 成就清单,已解锁的排在前面。"""
    all_reviews = {k: v for doc in docs.values() for k, v in (doc.get("reviews") or {}).items()}
    counts = progress(docs, goal_days_by_lang)

    rows = [
        {
            "key": a.key, "label": a.label, "detail": a.detail, "icon": a.icon,
            "target": a.target,
            "value": min(counts.get(a.key, 0), a.target),
            "unlocked": counts.get(a.key, 0) >= a.target,
            "percent": min(100, round(counts.get(a.key, 0) / a.target * 100)),
        }
        for a in ACHIEVEMENTS
    ]
    # 已解锁的排前面,未解锁的按接近程度排——下一个够得着的目标要显眼。
    rows.sort(key=lambda r: (not r["unlocked"], -r["percent"]))

    return {
        "level": level_of(mastered_count(all_reviews)),
        "achievements": rows,
        "unlocked": sum(1 for r in rows if r["unlocked"]),
        "total": len(rows),
    }
