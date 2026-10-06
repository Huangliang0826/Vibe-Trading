"""英语句型:内容清单与间隔重复逻辑。"""

import pytest

from src.growth.english import (
    FAST_MS, MAX_BOX, QUIZ_OPTIONS, apply_review, build_session, grade_for_answer,
    introduced_today, mark_studied, new_reviews, pick_quiz, shaky, stats,
)
from src.growth.english_patterns import (
    GROUPS, LEVEL_TOTALS, LEVELS, PATTERN_BY_ID, PATTERNS, TOTAL,
)

TODAY = "2026-10-05"


# ── 内容清单 ──────────────────────────────────────────────────────────────────

def test_the_catalog_has_all_three_levels_with_unique_ids():
    # ID 是复习进度的主键,重复会让两条句型共用一份记录。
    assert LEVEL_TOTALS == {"core": 100, "mid": 50, "high": 50}
    assert TOTAL == 200
    assert len(PATTERN_BY_ID) == 200


def test_new_patterns_are_introduced_easiest_first():
    # 新句型按清单顺序发,所以顺序本身就是难度梯度。
    levels = [p.level for p in PATTERNS]

    assert levels == sorted(levels, key=["core", "mid", "high"].index)


def test_every_pattern_carries_what_the_drill_needs():
    for p in PATTERNS:
        assert p.frame.strip(), p.id
        assert p.meaning.strip(), p.id
        # 没有中文情境提示就只能看着英文念,那是识别不是产出。
        assert p.cue.strip(), p.id
        assert len(p.examples) >= 2, p.id
        assert p.group in GROUPS, p.id
        assert p.level in LEVELS, p.id


def test_no_prompt_text_contains_english():
    # 情境和释义都是出题用的问句。混入英文,检索练习就退化成朗读;在测验里
    # 还可能直接指向某个选项。
    for p in PATTERNS:
        for field, text in (("cue", p.cue), ("meaning", p.meaning)):
            assert not any(ch.isascii() and ch.isalpha() for ch in text), (p.id, field, text)


def test_the_patterns_the_user_asked_for_are_all_present():
    wanted = ["I was wondering if", "It depends on", "The thing is", "I ended up",
              "It turns out", "not really into", "wouldn't say", "As far as I know"]
    frames = " | ".join(p.frame for p in PATTERNS).lower()

    missing = [w for w in wanted if w.lower() not in frames]
    assert missing == []


# ── 评分 ──────────────────────────────────────────────────────────────────────

def test_instant_recall_moves_the_pattern_up_a_box():
    reviews = apply_review(new_reviews(), "the-thing-is", "instant", TODAY)

    assert reviews["the-thing-is"]["box"] == 1
    assert reviews["the-thing-is"]["due"] == "2026-10-07"  # 第 1 盒 2 天


def test_a_slow_recall_keeps_the_box_but_schedules_it_again():
    reviews = apply_review(new_reviews(), "the-thing-is", "slow", TODAY)

    assert reviews["the-thing-is"]["box"] == 0
    assert reviews["the-thing-is"]["due"] == "2026-10-06"


def test_a_blank_sends_it_back_to_the_first_box_and_requeues_it_today():
    # 想不起来的句子等到明天才再见,这一轮就白练了。
    reviews = new_reviews()
    for _ in range(3):
        reviews = apply_review(reviews, "the-thing-is", "instant", TODAY)

    reviews = apply_review(reviews, "the-thing-is", "again", TODAY)

    assert reviews["the-thing-is"]["box"] == 0
    assert reviews["the-thing-is"]["due"] == TODAY


def test_only_a_run_of_instant_recalls_reaches_the_last_box():
    reviews = new_reviews()
    day = TODAY
    for _ in range(MAX_BOX + 2):
        reviews = apply_review(reviews, "the-thing-is", "instant", day)
        day = reviews["the-thing-is"]["due"]

    assert reviews["the-thing-is"]["box"] == MAX_BOX
    assert stats(reviews, day)["automatic"] == 1


def test_a_slow_answer_never_counts_as_automatic():
    reviews = new_reviews()
    day = TODAY
    for _ in range(8):
        reviews = apply_review(reviews, "the-thing-is", "slow", day)
        day = reviews["the-thing-is"]["due"]

    assert stats(reviews, day)["automatic"] == 0


def test_review_counts_attempts_and_keeps_the_first_date():
    reviews = apply_review(new_reviews(), "the-thing-is", "slow", TODAY)
    reviews = apply_review(reviews, "the-thing-is", "instant", "2026-10-09")

    assert reviews["the-thing-is"]["seen"] == 2
    assert reviews["the-thing-is"]["first"] == TODAY
    assert reviews["the-thing-is"]["last"] == "2026-10-09"


def test_review_rejects_an_unknown_pattern_or_grade():
    with pytest.raises(ValueError, match="没有这个句型"):
        apply_review(new_reviews(), "nope", "instant", TODAY)
    with pytest.raises(ValueError, match="评分"):
        apply_review(new_reviews(), "the-thing-is", "perfect", TODAY)


# ── 每日练习的组成 ────────────────────────────────────────────────────────────

def test_the_first_session_offers_the_whole_catalog_when_unlimited():
    # 每天学多少由自己定,所以默认不设上限。
    session = build_session(new_reviews(), TODAY)

    assert len(session) == TOTAL
    assert {item["status"] for item in session} == {"new"}


def test_caps_still_apply_when_asked_for_explicitly():
    session = build_session(new_reviews(), TODAY, new_per_day=8, limit=20)

    assert len(session) == 8


def test_an_unlimited_session_still_puts_due_reviews_first():
    reviews = new_reviews()
    for pid in list(PATTERN_BY_ID)[:5]:
        reviews = apply_review(reviews, pid, "again", TODAY)

    session = build_session(reviews, TODAY)

    assert [item["status"] for item in session[:5]] == ["review"] * 5
    assert len(session) == TOTAL


def test_due_reviews_come_before_new_material():
    # 积压的复习才是记忆真正流失的地方,新鲜感不该排在它前面。
    reviews = new_reviews()
    for pid in list(PATTERN_BY_ID)[:5]:
        reviews = apply_review(reviews, pid, "again", TODAY)

    session = build_session(reviews, TODAY, new_per_day=8, limit=6)

    assert [item["status"] for item in session[:5]] == ["review"] * 5
    assert len(session) == 6


def test_new_material_stops_once_the_daily_budget_is_used_up():
    reviews = new_reviews()
    for pid in list(PATTERN_BY_ID)[:8]:
        reviews = apply_review(reviews, pid, "instant", TODAY)

    assert introduced_today(reviews, TODAY) == 8
    # 显式设了额度就按额度来,用完当天只剩到期的复习。
    session = build_session(reviews, TODAY, new_per_day=8, limit=20)
    assert all(item["status"] == "review" for item in session)


def test_the_budget_refreshes_the_next_day():
    reviews = new_reviews()
    for pid in list(PATTERN_BY_ID)[:8]:
        reviews = apply_review(reviews, pid, "instant", TODAY)

    session = build_session(reviews, "2026-10-06", new_per_day=8, limit=20)

    assert any(item["status"] == "new" for item in session)


def test_a_pattern_scheduled_for_later_stays_out_of_todays_session():
    reviews = apply_review(new_reviews(), "the-thing-is", "instant", TODAY)

    session = build_session(reviews, TODAY, new_per_day=0, limit=20)

    assert session == []


# ── 进度 ──────────────────────────────────────────────────────────────────────

def test_stats_report_progress_towards_the_whole_catalog():
    reviews = apply_review(new_reviews(), "the-thing-is", "instant", TODAY)

    s = stats(reviews, TODAY)

    assert s["total"] == TOTAL and s["started"] == 1 and s["automatic"] == 0
    assert s["reviewed_today"] == 1


def test_shaky_lists_patterns_that_are_practised_a_lot_but_still_stuck():
    reviews = new_reviews()
    for _ in range(4):
        reviews = apply_review(reviews, "the-thing-is", "again", TODAY)
    reviews = apply_review(reviews, "it-depends-on", "instant", TODAY)

    rows = shaky(reviews)

    assert [r["id"] for r in rows] == ["the-thing-is"]
    assert rows[0]["seen"] == 4


# ── 测验:两选一,对错由客观作答决定 ──────────────────────────────────────────

def _rng(seed=7):
    import random
    return random.Random(seed)


def test_each_question_offers_exactly_two_cards_one_of_them_right():
    questions = pick_quiz(new_reviews(), TODAY, count=5, rng=_rng())

    assert len(questions) == 5
    for q in questions:
        assert len(q["options"]) == QUIZ_OPTIONS
        ids = [o["id"] for o in q["options"]]
        assert q["answer_id"] in ids
        assert len(set(ids)) == QUIZ_OPTIONS


def test_the_distractor_comes_from_the_same_functional_group():
    # 不同组的两张卡一眼就能排除,考不出分辨力。
    questions = pick_quiz(new_reviews(), TODAY, count=20, rng=_rng())

    for q in questions:
        groups = {PATTERN_BY_ID[o["id"]].group for o in q["options"]}
        assert len(groups) == 1, q


def test_the_question_carries_the_answers_unique_gloss():
    q = pick_quiz(new_reviews(), TODAY, count=1, rng=_rng())[0]
    answer = PATTERN_BY_ID[q["answer_id"]]

    assert q["meaning"] == answer.meaning and q["cue"] == answer.cue
    assert q["group_label"] and q["level_label"]


def test_every_pattern_has_a_distinct_gloss_so_each_question_has_one_answer():
    # 同组的句型常是近义的。只给情境会出歧义题("不确定但要给个数"既可以是
    # I'd say 也可以是 I'm not sure, but),所以问句以释义为主——它必须唯一。
    meanings = [p.meaning for p in PATTERNS]

    assert len(set(meanings)) == len(meanings)


def test_a_questions_two_options_never_share_a_gloss():
    for q in pick_quiz(new_reviews(), TODAY, count=30, rng=_rng()):
        glosses = {PATTERN_BY_ID[o["id"]].meaning for o in q["options"]}
        assert len(glosses) == 2, q


def test_due_patterns_are_asked_before_the_rest():
    reviews = new_reviews()
    for pid in list(PATTERN_BY_ID)[:3]:
        reviews = apply_review(reviews, pid, "again", TODAY)  # due 今天
    for pid in list(PATTERN_BY_ID)[3:9]:
        reviews = apply_review(reviews, pid, "instant", TODAY)  # 排到以后

    asked = [q["answer_id"] for q in pick_quiz(reviews, TODAY, count=3, rng=_rng())]

    assert set(asked) == set(list(PATTERN_BY_ID)[:3])


def test_the_quiz_falls_back_to_the_whole_catalog_before_anything_is_studied():
    # 第一次打开就该能玩起来,边考边学好过一个空页面。
    assert len(pick_quiz(new_reviews(), TODAY, count=10, rng=_rng())) == 10


def test_the_quiz_draws_only_from_what_has_been_seen_once_enough_is_studied():
    reviews = new_reviews()
    studied = list(PATTERN_BY_ID)[:6]
    for pid in studied:
        reviews = mark_studied(reviews, pid, TODAY)

    asked = {q["answer_id"] for q in pick_quiz(reviews, TODAY, count=20, rng=_rng())}

    assert asked <= set(studied)


# ── 客观评分 ──────────────────────────────────────────────────────────────────

def test_a_wrong_answer_is_graded_as_a_blank_however_fast_it_was():
    assert grade_for_answer(False, 200) == "again"


def test_a_fast_correct_answer_counts_as_automatic():
    assert grade_for_answer(True, FAST_MS - 1) == "instant"


def test_a_slow_correct_answer_does_not_move_the_box_up():
    # 慢慢推出来的正确答案,在真实对话里仍然是卡壳。
    assert grade_for_answer(True, FAST_MS + 1) == "slow"


def test_marking_a_pattern_studied_records_exposure_without_scoring_it():
    reviews = mark_studied(new_reviews(), "the-thing-is", TODAY)

    entry = reviews["the-thing-is"]
    assert entry["studied"] == TODAY
    assert "box" not in entry and "seen" not in entry
    assert stats(reviews, TODAY)["tested"] == 0


def test_studying_twice_keeps_the_first_date(
):
    reviews = mark_studied(new_reviews(), "the-thing-is", TODAY)
    reviews = mark_studied(reviews, "the-thing-is", "2026-10-09")

    assert reviews["the-thing-is"]["studied"] == TODAY


def test_a_quiz_answer_keeps_the_studied_mark():
    reviews = mark_studied(new_reviews(), "the-thing-is", TODAY)

    reviews = apply_review(reviews, "the-thing-is", "instant", TODAY)

    assert reviews["the-thing-is"]["studied"] == TODAY
    assert reviews["the-thing-is"]["box"] == 1


def test_stats_track_quiz_accuracy():
    reviews = apply_review(new_reviews(), "the-thing-is", "instant", TODAY)
    reviews = apply_review(reviews, "it-depends-on", "again", TODAY)
    reviews = apply_review(reviews, "the-point-is", "slow", TODAY)

    s = stats(reviews, TODAY)

    assert s["tested"] == 3
    assert s["accuracy"] == 67  # 3 次作答里 2 次选对


def test_accuracy_is_absent_before_any_answer():
    assert stats(mark_studied(new_reviews(), "the-thing-is", TODAY), TODAY)["accuracy"] is None
