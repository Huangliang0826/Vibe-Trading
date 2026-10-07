"""练习引擎:间隔重复 + 两选一测验——全是纯函数,与具体语言无关。

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

from src.growth.languages import CATALOGS, DEFAULT_LANG, catalog, daily_goal


def _patterns(lang: str, track: str) -> tuple:
    cat = catalog(lang)
    if track not in cat.by_track:
        raise ValueError(f"{cat.label}没有这个分类:{track}")
    return cat.by_track[track]


def default_track(lang: str) -> str:
    """该语言的第一个分类。荷兰语没有句型,所以不能把 frame 写死成默认值。"""
    return catalog(lang).tracks[0]

GRADES = ("again", "slow", "instant")

#: 测验里每题给几张卡片。两张:够快到可以一指一题,又真的要分辨。
QUIZ_OPTIONS = 2

#: 答对多快才算"脱口而出"。读一句中文情境加扫两个英文框架,大约三四秒;
#: 超过六秒说明是推理出来的,不是调用出来的——那还不叫自动化,所以不升盒。
FAST_MS = 6000

#: 第 0~4 盒的复习间隔(天)。最后一盒 21 天仍能脱口而出,才算真的固化。
INTERVALS = (1, 2, 4, 9, 21)
MAX_BOX = len(INTERVALS) - 1



def _add_days(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def new_reviews() -> dict:
    return {}


def find_pattern(pattern_id: str):
    """按 id 跨语言找条目。id 全局唯一,所以按 id 操作的接口不必带语言参数。"""
    for lang in CATALOGS:
        pattern = catalog(lang).by_id.get(pattern_id)
        if pattern is not None:
            return pattern
    return None


def mark_studied(reviews: dict, pattern_id: str, today: str) -> dict:
    """在学习页看过一条。只记接触,不记分——打分是测验的事。"""
    if find_pattern(pattern_id) is None:
        raise ValueError(f"没有这个条目:{pattern_id}")
    entry = dict(reviews.get(pattern_id) or {})
    return {**reviews, pattern_id: {**entry, "studied": entry.get("studied") or today}}


def record_answer(doc: dict, pattern_id: str, correct: bool, elapsed_ms: int, today: str) -> dict:
    """记一次测试作答:推进复习盒子,同时累加当天的战绩。

    两件事一起返回一份新文档,由调用方一次写盘——分开写就会出现盒子已经动了
    但当天计数还没加上的中间状态,日历也就跟着错一天。
    """
    reviews = apply_review(doc.get("reviews") or {}, pattern_id,
                           grade_for_answer(correct, elapsed_ms), today)
    day = dict((doc.get("daily") or {}).get(today) or {})
    day["answered"] = int(day.get("answered", 0)) + 1
    day["correct"] = int(day.get("correct", 0)) + (1 if correct else 0)
    return {**doc, "reviews": reviews, "daily": {**(doc.get("daily") or {}), today: day}}


def today_progress(doc: dict, today: str, lang: str = DEFAULT_LANG) -> dict:
    """今天这门语言的进度——「每天」那张卡片要显示的东西。"""
    goal = daily_goal(lang)
    day = (doc.get("daily") or {}).get(today) or {}
    correct = int(day.get("correct", 0))
    return {
        "lang": lang,
        "goal": goal,
        "correct": correct,
        "answered": int(day.get("answered", 0)),
        "done": correct >= goal,
    }


def goal_days(doc: dict, lang: str = DEFAULT_LANG) -> set[str]:
    """达成过当天目标的日期。"""
    goal = daily_goal(lang)
    return {
        day for day, row in (doc.get("daily") or {}).items()
        if int((row or {}).get("correct", 0)) >= goal
    }


def set_favorite(reviews: dict, pattern_id: str, favorite: bool) -> dict:
    """收藏 / 取消收藏一条句型。

    与盒子无关:盒子是算法按答题表现推的,收藏是自己标的"这句我要留着"。
    两件事互不干涉,所以收藏不会打乱复习节奏。
    """
    if find_pattern(pattern_id) is None:
        raise ValueError(f"没有这个条目:{pattern_id}")
    entry = dict(reviews.get(pattern_id) or {})
    if favorite:
        entry["favorite"] = True
    else:
        entry.pop("favorite", None)
    return {**reviews, pattern_id: entry}


def favorites(reviews: dict, lang: str, track: str) -> list[dict]:
    """已收藏的条目,按清单顺序(也就是难度顺序)。"""
    return [
        {
            "id": p.id, "frame": p.frame, "meaning": p.meaning,
            "group_label": p.group_label, "level_label": p.level_label,
        }
        for p in _patterns(lang, track)
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
    if find_pattern(pattern_id) is None:
        raise ValueError(f"没有这个条目:{pattern_id}")
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


def _quiz_pool(reviews: dict, lang: str, track: str) -> list:
    """可以拿来考的条目:学习页见过的,或已经考过的。

    都没有时退回整条线(按难度顺序),这样第一次打开测验也能玩起来——
    边考边学,总好过一个空页面。
    """
    patterns = _patterns(lang, track)
    known = [p for p in patterns if p.id in reviews]
    return known if len(known) >= QUIZ_OPTIONS else list(patterns)


def pick_quiz(reviews: dict, today: str, *, lang: str, track: str, count: int = 20,
              rng: random.Random | None = None) -> list[dict]:
    """抽一批题。到期的优先,其余随机——重复的题面会让人开始背位置而不是背内容。"""
    rng = rng or random.Random()
    pool = _quiz_pool(reviews, lang, track)
    if len(pool) < QUIZ_OPTIONS:
        return []

    def is_due(p) -> bool:
        # 必须真的有 due 才算到期。缺字段时取默认空串会比任何日期都小,
        # 把"只是看过、还没考过"的条目误判成到期。
        due = (reviews.get(p.id) or {}).get("due")
        return bool(due) and str(due) <= today

    due_now = [p for p in pool if is_due(p)]
    rest = [p for p in pool if not is_due(p)]
    rng.shuffle(due_now)
    rng.shuffle(rest)
    asked = (due_now + rest)[:count]

    questions = []
    for answer in asked:
        if answer.wrong:
            # 搭配:干扰项用中式英语的直译版。打的正是"逐词翻译"这个习惯本身,
            # 错一次的印象远比读十遍正确答案深。
            options = [
                {"id": answer.id, "frame": answer.frame, "meaning": answer.meaning},
                {"id": f"{answer.id}#wrong", "frame": rng.choice(answer.wrong),
                 "meaning": "直译,英语里不这么说"},
            ]
        else:
            # 干扰项取同一个功能分组——不同组的两张卡一眼就能排除,考不出分辨力。
            same_group = [p for p in pool if p.group == answer.group and p.id != answer.id]
            others = same_group or [p for p in pool if p.id != answer.id]
            distractor = rng.choice(others)
            options = [
                {"id": o["id"], "frame": o["frame"], "meaning": o["meaning"]}
                for o in (answer.to_dict(), distractor.to_dict())
            ]
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
            "options": options,
        })
    return questions


def build_session(reviews: dict, today: str, *, lang: str, track: str,
                  limit: int | None = None) -> list[dict]:
    """学习页的队列:**还没看过的**句型,按清单顺序(也就是难度顺序)。

    于是进度天然是续着的——看过一条就记一条 ``studied``,下次打开从第一条
    没看过的开始。

    这里曾经混进"到期复习",但只标了 studied 的条目没有 ``due`` 字段,取默认值
    得到空字符串,而空字符串比任何日期都小,于是被判成到期、永远排在最前面:
    每次打开都从第一条重新学。复习归测试页管,这一页只负责往下推。
    """
    fresh = [p for p in _patterns(lang, track)
             if not (reviews.get(p.id) or {}).get("studied")]
    if limit is not None:
        fresh = fresh[:limit]
    return [
        {**p.to_dict(), "status": "new", "box": 0, "seen": 0,
         "favorite": bool((reviews.get(p.id) or {}).get("favorite"))}
        for p in fresh
    ]


def stats(reviews: dict, today: str, lang: str, track: str) -> dict:
    """某条线的进度总览。"""
    mine = {p.id for p in _patterns(lang, track)}
    reviews = {k: v for k, v in reviews.items() if k in mine}
    tested = [e for e in reviews.values() if int(e.get("seen", 0)) > 0]
    boxes = [int(e.get("box", 0)) for e in tested]
    right = sum(int(e.get("right", 0)) for e in tested)
    wrong = sum(int(e.get("wrong", 0)) for e in tested)
    return {
        "lang": lang,
        "track": track,
        "total": len(_patterns(lang, track)),
        "started": len(reviews),
        "favorites": sum(1 for e in reviews.values() if e.get("favorite")),
        "tested": len(tested),
        "accuracy": round(right / (right + wrong) * 100) if right + wrong else None,
        "automatic": sum(1 for b in boxes if b >= MAX_BOX),
        "due_today": sum(1 for e in tested if str(e.get("due", "")) <= today),
        "reviewed_today": sum(1 for e in reviews.values() if e.get("last") == today),
        "box_counts": {str(b): boxes.count(b) for b in range(len(INTERVALS))},
    }
