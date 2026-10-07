"""等级与成就:奖励必须挂在真实掌握度上,不能奖励点击次数。"""

from src.growth.practice import MAX_BOX
from src.growth.rewards import LEVELS, build_rewards, level_of, mastered_count, progress

TODAY = "2026-10-07"


def _doc(reviews=None, daily=None):
    return {"reviews": reviews or {}, "daily": daily or {}}


def _mastered(n, **extra):
    return {f"p{i}": {"box": MAX_BOX, **extra} for i in range(n)}


# ── 等级 ──────────────────────────────────────────────────────────────────────

def test_level_counts_only_items_in_the_last_box():
    # 进最后一盒要在 21 天间隔后仍然六秒内答对,答错一次就退回第一盒。
    # 别的计数(看过、答过)都能靠点击堆出来,只有这个不能。
    reviews = {"a": {"box": MAX_BOX}, "b": {"box": MAX_BOX - 1}, "c": {"seen": 99, "box": 0}}

    assert mastered_count(reviews) == 1


def test_the_first_level_starts_at_zero():
    assert level_of(0)["level"] == 1 and level_of(0)["label"] == LEVELS[0][1]


def test_crossing_a_threshold_moves_up_a_level():
    assert level_of(9)["label"] == "起步"
    assert level_of(10)["label"] == "上手"


def test_the_level_reports_how_far_the_next_one_is():
    info = level_of(12)

    assert info["next_at"] == 30 and info["to_next"] == 18
    assert 0 < info["percent"] < 100


def test_the_top_level_has_nothing_left_to_reach():
    info = level_of(10_000)

    assert info["next_at"] is None and info["to_next"] == 0 and info["percent"] == 100


# ── 成就 ──────────────────────────────────────────────────────────────────────

def test_nothing_is_unlocked_on_a_blank_slate():
    rewards = build_rewards({"en": _doc()}, {"en": set()})

    assert rewards["unlocked"] == 0
    assert all(not a["unlocked"] for a in rewards["achievements"])


def test_a_single_answer_unlocks_the_first_one():
    rewards = build_rewards({"en": _doc(daily={TODAY: {"answered": 1, "correct": 0}})},
                            {"en": set()})

    first = next(a for a in rewards["achievements"] if a["key"] == "first_quiz")
    assert first["unlocked"] is True


def test_a_streak_achievement_uses_the_longest_run_ever():
    days = {f"2026-09-{d:02d}" for d in range(1, 8)}

    rewards = build_rewards({"en": _doc()}, {"en": days})

    by_key = {a["key"]: a for a in rewards["achievements"]}
    assert by_key["streak_7"]["unlocked"] is True
    assert by_key["streak_14"]["unlocked"] is False and by_key["streak_14"]["value"] == 7


def test_a_broken_run_does_not_count_as_a_streak():
    days = {"2026-09-01", "2026-09-02", "2026-09-04", "2026-09-05"}

    by_key = {a["key"]: a for a in build_rewards({"en": _doc()}, {"en": days})["achievements"]}
    assert by_key["streak_7"]["value"] == 2


def test_the_comeback_achievement_needs_both_a_miss_and_mastery():
    # 一次就会的不算本事,错过又记牢了才算。
    reviews = {
        "never_wrong": {"box": MAX_BOX, "wrong": 0},
        "still_stuck": {"box": 1, "wrong": 5},
        "came_back": {"box": MAX_BOX, "wrong": 3},
    }

    assert progress({"en": _doc(reviews)}, {})["comeback_10"] == 1


def test_bilingual_day_needs_both_languages_on_the_same_day():
    days = {"en": {"2026-10-05", "2026-10-07"}, "nl": {"2026-10-07"}}

    counts = progress({"en": _doc(), "nl": _doc()}, days)
    assert counts["bilingual_day"] == 1


def test_progress_adds_up_across_languages():
    docs = {"en": _doc(_mastered(6)), "nl": _doc({f"n{i}": {"box": MAX_BOX} for i in range(5)})}

    assert build_rewards(docs, {})["level"]["mastered"] == 11


def test_dutch_achievement_ignores_english_progress():
    docs = {
        "en": _doc({f"e{i}": {"studied": TODAY} for i in range(80)}),
        "nl": _doc({f"n{i}": {"studied": TODAY} for i in range(3)}),
    }

    assert progress(docs, {})["dutch_50"] == 3


def test_unlocked_achievements_are_listed_first_then_the_closest_ones():
    docs = {"en": _doc(_mastered(10, studied=TODAY),
                       daily={TODAY: {"answered": 5, "correct": 5}})}

    rows = build_rewards(docs, {"en": {TODAY}})["achievements"]
    unlocked = [i for i, r in enumerate(rows) if r["unlocked"]]
    locked = [i for i, r in enumerate(rows) if not r["unlocked"]]

    assert max(unlocked) < min(locked)
    # 未解锁的里面,够得着的排在前面。
    percents = [rows[i]["percent"] for i in locked]
    assert percents == sorted(percents, reverse=True)


def test_a_value_never_exceeds_its_target():
    docs = {"en": _doc(_mastered(500))}

    assert all(a["value"] <= a["target"] for a in build_rewards(docs, {})["achievements"])
