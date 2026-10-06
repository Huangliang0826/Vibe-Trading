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

import random
from datetime import date, timedelta

from src.growth.english_patterns import PATTERN_BY_ID, PATTERNS, TOTAL

GRADES = ("again", "slow", "instant")

#: 测验里每题给几张卡片。两张:够快到可以一指一题,又真的要分辨。
QUIZ_OPTIONS = 2

#: 答对多快才算"脱口而出"。读一句中文情境加扫两个英文框架,大约三四秒;
#: 超过六秒说明是推理出来的,不是调用出来的——那还不叫自动化,所以不升盒。
FAST_MS = 6000

#: 第 0~4 盒的复习间隔(天)。最后一盒 21 天仍能脱口而出,才算真的固化。
INTERVALS = (1, 2, 4, 9, 21)
MAX_BOX = len(INTERVALS) - 1

#: 每天引入多少新句型、单轮练多少条,都不设上限(``None``)——想练多少练多少。
#: 两个参数保留下来是因为顺序仍然有意义:到期的复习永远排在新内容前面。
NEW_PER_DAY: int | None = None
SESSION_LIMIT: int | None = None


def _add_days(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def new_reviews() -> dict:
    return {}


def mark_studied(reviews: dict, pattern_id: str, today: str) -> dict:
    """在学习页看过一条。只记接触,不记分——打分是测验的事。"""
    if pattern_id not in PATTERN_BY_ID:
        raise ValueError(f"没有这个句型:{pattern_id}")
    entry = dict(reviews.get(pattern_id) or {})
    return {**reviews, pattern_id: {**entry, "studied": entry.get("studied") or today}}


def set_favorite(reviews: dict, pattern_id: str, favorite: bool) -> dict:
    """收藏 / 取消收藏一条句型。

    与盒子无关:盒子是算法按答题表现推的,收藏是自己标的"这句我要留着"。
    两件事互不干涉,所以收藏不会打乱复习节奏。
    """
    if pattern_id not in PATTERN_BY_ID:
        raise ValueError(f"没有这个句型:{pattern_id}")
    entry = dict(reviews.get(pattern_id) or {})
    if favorite:
        entry["favorite"] = True
    else:
        entry.pop("favorite", None)
    return {**reviews, pattern_id: entry}


def favorites(reviews: dict) -> list[dict]:
    """已收藏的句型,按清单顺序(也就是难度顺序)。"""
    return [
        {
            "id": p.id, "frame": p.frame, "meaning": p.meaning,
            "group_label": p.group_label, "level_label": p.level_label,
        }
        for p in PATTERNS
        if (reviews.get(p.id) or {}).get("favorite")
    ]


def grade_for_answer(correct: bool, elapsed_ms: int) -> str:
    """把一次客观作答翻译成盒子评分。

    答错就是答错;答对还要看快慢——慢慢推出来的正确答案,在真实对话里仍然
    是卡壳,所以只留在原盒,不往上走。
    """
    if not correct:
        return "again"
    return "instant" if elapsed_ms <= FAST_MS else "slow"


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
            **entry,
            "box": box,
            "due": due,
            "seen": int(entry.get("seen", 0)) + 1,
            "first": entry.get("first") or today,
            "last": today,
            # 记录最后一次的手感,用于"还卡壳的句型"清单。
            "last_grade": grade,
            "right": int(entry.get("right", 0)) + (1 if grade != "again" else 0),
            "wrong": int(entry.get("wrong", 0)) + (1 if grade == "again" else 0),
        },
    }


def _quiz_pool(reviews: dict) -> list:
    """可以拿来考的句型:学习页见过的,或已经考过的。

    都没有时退回整份清单(按难度顺序),这样第一次打开测验也能玩起来——
    边考边学,总好过一个空页面。
    """
    known = [p for p in PATTERNS if p.id in reviews]
    return known if len(known) >= QUIZ_OPTIONS else list(PATTERNS)


def pick_quiz(reviews: dict, today: str, *, count: int = 20,
              rng: random.Random | None = None) -> list[dict]:
    """抽一批题。到期的优先,其余随机——重复的题面会让人开始背位置而不是背句型。"""
    rng = rng or random.Random()
    pool = _quiz_pool(reviews)
    if len(pool) < QUIZ_OPTIONS:
        return []

    def is_due(p) -> bool:
        entry = reviews.get(p.id)
        return bool(entry) and str(entry.get("due", "")) <= today

    due_now = [p for p in pool if is_due(p)]
    rest = [p for p in pool if not is_due(p)]
    rng.shuffle(due_now)
    rng.shuffle(rest)
    asked = (due_now + rest)[:count]

    questions = []
    for answer in asked:
        # 干扰项取同一个功能分组——不同组的两张卡一眼就能排除,考不出分辨力。
        same_group = [p for p in pool if p.group == answer.group and p.id != answer.id]
        others = same_group or [p for p in pool if p.id != answer.id]
        distractor = rng.choice(others)
        options = [answer.to_dict(), distractor.to_dict()]
        rng.shuffle(options)
        questions.append({
            "answer_id": answer.id,
            # 问句以释义为主:同组的句型常是近义的,只给情境会出歧义题——
            # "不确定但要给个数"既可以是 I'd say,也可以是 I'm not sure, but。
            # 释义在 200 条里唯一,所以每题恰好一个正确答案。
            "meaning": answer.meaning,
            "cue": answer.cue,
            "group_label": answer.group_label,
            "level_label": answer.level_label,
            "options": [{"id": o["id"], "frame": o["frame"], "meaning": o["meaning"]}
                        for o in options],
        })
    return questions


def introduced_today(reviews: dict, today: str) -> int:
    return sum(1 for e in reviews.values() if e.get("first") == today)


def build_session(reviews: dict, today: str, *, new_per_day: int | None = NEW_PER_DAY,
                  limit: int | None = SESSION_LIMIT) -> list[dict]:
    """今天要练的条目:先清到期的,再补新的。

    到期的永远优先于新的——积压的复习才是记忆真正流失的地方,新鲜感不该
    排在它前面。``new_per_day`` 与 ``limit`` 为 ``None`` 表示不限量。
    """
    due = [
        (entry, PATTERN_BY_ID[pid])
        for pid, entry in reviews.items()
        if pid in PATTERN_BY_ID and str(entry.get("due", "")) <= today
    ]
    due.sort(key=lambda pair: (str(pair[0].get("due", "")), int(pair[0].get("box", 0))))

    items = [
        {**pattern.to_dict(), "status": "review", "box": int(entry.get("box", 0)),
         "seen": int(entry.get("seen", 0)), "favorite": bool(entry.get("favorite"))}
        for entry, pattern in (due if limit is None else due[:limit])
    ]

    room = None if limit is None else max(0, limit - len(items))
    budget = None if new_per_day is None else max(0, new_per_day - introduced_today(reviews, today))
    if room == 0 or budget == 0:
        return items

    fresh = [p for p in PATTERNS if p.id not in reviews]
    caps = [c for c in (room, budget) if c is not None]
    if caps:
        fresh = fresh[: min(caps)]
    return items + [
        {**p.to_dict(), "status": "new", "box": 0, "seen": 0,
         "favorite": bool((reviews.get(p.id) or {}).get("favorite"))}
        for p in fresh
    ]


def stats(reviews: dict, today: str) -> dict:
    """进度总览。``automatic`` 是真正要追的那个数字。"""
    tested = [e for e in reviews.values() if int(e.get("seen", 0)) > 0]
    boxes = [int(e.get("box", 0)) for e in tested]
    right = sum(int(e.get("right", 0)) for e in tested)
    wrong = sum(int(e.get("wrong", 0)) for e in tested)
    return {
        "total": TOTAL,
        "started": len(reviews),
        "favorites": sum(1 for e in reviews.values() if e.get("favorite")),
        "tested": len(tested),
        "accuracy": round(right / (right + wrong) * 100) if right + wrong else None,
        "automatic": sum(1 for b in boxes if b >= MAX_BOX),
        "due_today": sum(1 for e in tested if str(e.get("due", "")) <= today),
        "reviewed_today": sum(1 for e in reviews.values() if e.get("last") == today),
        "box_counts": {str(b): boxes.count(b) for b in range(len(INTERVALS))},
    }
