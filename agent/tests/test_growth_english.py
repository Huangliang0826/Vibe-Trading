"""英语句型:内容清单与间隔重复逻辑。"""

import pytest

from src.growth.english import (
    DAILY_GOAL, FAST_MS, MAX_BOX, QUIZ_OPTIONS, apply_review, build_session,
    english_days, english_today, favorites, grade_for_answer, mark_studied,
    new_reviews, pick_quiz, record_answer, set_favorite, stats,
)
from src.growth.english_patterns import (
    GROUPS, LEVELS, PATTERN_BY_ID, PATTERNS, PATTERNS_BY_TRACK, TOTAL,
    TRACK_TOTALS, TRACKS,
)

FRAMES = PATTERNS_BY_TRACK["frame"]

TODAY = "2026-10-05"


# ── 内容清单 ──────────────────────────────────────────────────────────────────

def test_the_catalog_has_three_tracks_with_unique_ids():
    # ID 是复习进度的主键,重复会让两条内容共用一份记录。
    assert set(TRACKS) == {"frame", "oneliner", "collocation"}
    assert sum(TRACK_TOTALS.values()) == TOTAL
    assert len(PATTERN_BY_ID) == TOTAL


def test_each_track_is_introduced_easiest_first():
    # 新内容按清单顺序发,所以每条线内部的顺序就是难度梯度。
    for track, items in PATTERNS_BY_TRACK.items():
        levels = [p.level for p in items]
        assert levels == sorted(levels, key=["core", "mid", "high"].index), track


def test_a_frame_has_a_slot_and_a_one_liner_does_not():
    # 省略号就是两条线的分界:有空位要填的是句型,没有的本身就是一句完整的话。
    assert all("…" in p.frame for p in PATTERNS_BY_TRACK["frame"])
    assert all("…" not in p.frame for p in PATTERNS_BY_TRACK["oneliner"])


def test_every_collocation_carries_a_chinglish_distractor():
    for p in PATTERNS_BY_TRACK["collocation"]:
        assert p.wrong, p.id
        assert p.frame not in p.wrong, p.id


def test_only_collocations_carry_wrong_versions():
    for track in ("frame", "oneliner"):
        assert all(not p.wrong for p in PATTERNS_BY_TRACK[track]), track


def test_every_pattern_carries_what_the_drill_needs():
    for p in PATTERNS:
        assert p.frame.strip(), p.id
        assert p.meaning.strip(), p.id
        # 没有中文情境提示就只能看着英文念,那是识别不是产出。
        assert p.cue.strip(), p.id
        assert len(p.examples) >= 2, p.id
        assert p.group in GROUPS[p.track], p.id
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


# ── 进度 ──────────────────────────────────────────────────────────────────────

def test_stats_report_progress_within_one_track():
    reviews = apply_review(new_reviews(), "the-thing-is", "instant", TODAY)

    s = stats(reviews, TODAY)

    assert s["total"] == TRACK_TOTALS["frame"] and s["started"] == 1
    # 另一条线的进度不该被算进来。
    assert stats(reviews, TODAY, "collocation")["started"] == 0
    assert s["reviewed_today"] == 1



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


# ── 收藏 ──────────────────────────────────────────────────────────────────────

def test_favoriting_a_pattern_lists_it_and_counts_it():
    reviews = set_favorite(new_reviews(), "the-thing-is", True)

    assert [f["id"] for f in favorites(reviews)] == ["the-thing-is"]
    assert stats(reviews, TODAY)["favorites"] == 1


def test_unfavoriting_removes_it():
    reviews = set_favorite(new_reviews(), "the-thing-is", True)

    reviews = set_favorite(reviews, "the-thing-is", False)

    assert favorites(reviews) == [] and stats(reviews, TODAY)["favorites"] == 0


def test_favoriting_does_not_disturb_the_review_schedule():
    # 盒子是算法按答题表现推的,收藏是自己标的。两件事不该互相干涉。
    reviews = apply_review(new_reviews(), "the-thing-is", "instant", TODAY)
    before = dict(reviews["the-thing-is"])

    reviews = set_favorite(reviews, "the-thing-is", True)

    entry = reviews["the-thing-is"]
    assert {k: v for k, v in entry.items() if k != "favorite"} == before
    assert entry["favorite"] is True


def test_favoriting_an_unseen_pattern_does_not_count_it_as_tested():
    reviews = set_favorite(new_reviews(), "the-thing-is", True)

    s = stats(reviews, TODAY)
    assert s["favorites"] == 1 and s["tested"] == 0


def test_favorites_are_listed_easiest_first():
    reviews = set_favorite(new_reviews(), "high-be-that-as-it-may", True)
    reviews = set_favorite(reviews, "the-thing-is", True)

    assert [f["level_label"] for f in favorites(reviews)] == ["基础", "高级"]


def test_session_items_carry_their_favorite_state():
    reviews = set_favorite(new_reviews(), "the-thing-is", True)

    by_id = {item["id"]: item for item in build_session(reviews, TODAY)}

    assert by_id["the-thing-is"]["favorite"] is True
    assert by_id["it-depends-on"]["favorite"] is False


def test_favoriting_rejects_an_unknown_pattern():
    with pytest.raises(ValueError, match="没有这个句型"):
        set_favorite(new_reviews(), "nope", True)


# ── 每天的英语目标 ────────────────────────────────────────────────────────────

def test_a_quiz_answer_counts_towards_todays_goal():
    doc = {"reviews": {}, "daily": {}}

    doc = record_answer(doc, "the-thing-is", True, 900, TODAY)

    assert english_today(doc, TODAY) == {"goal": DAILY_GOAL, "correct": 1, "answered": 1, "done": False}


def test_a_wrong_answer_counts_as_answered_but_not_as_progress():
    doc = record_answer({"reviews": {}, "daily": {}}, "the-thing-is", False, 900, TODAY)

    progress = english_today(doc, TODAY)
    assert progress["answered"] == 1 and progress["correct"] == 0


def test_the_day_is_done_once_the_goal_is_reached():
    doc = {"reviews": {}, "daily": {}}
    for _ in range(DAILY_GOAL):
        doc = record_answer(doc, "the-thing-is", True, 900, TODAY)

    assert english_today(doc, TODAY)["done"] is True
    assert english_days(doc) == {TODAY}


def test_a_day_short_of_the_goal_is_not_marked_on_the_calendar():
    doc = {"reviews": {}, "daily": {}}
    for _ in range(DAILY_GOAL - 1):
        doc = record_answer(doc, "the-thing-is", True, 900, TODAY)

    assert english_days(doc) == set()


def test_each_day_is_counted_separately():
    doc = {"reviews": {}, "daily": {}}
    for _ in range(DAILY_GOAL):
        doc = record_answer(doc, "the-thing-is", True, 900, "2026-10-05")
    doc = record_answer(doc, "the-thing-is", True, 900, "2026-10-06")

    assert english_days(doc) == {"2026-10-05"}
    assert english_today(doc, "2026-10-06")["correct"] == 1


def test_an_answer_advances_the_box_and_the_daily_tally_together():
    # 分成两次写盘会出现盒子动了但当天计数没加的中间状态,日历就跟着错一天。
    doc = record_answer({"reviews": {}, "daily": {}}, "the-thing-is", True, 900, TODAY)

    assert doc["reviews"]["the-thing-is"]["box"] == 1
    assert doc["daily"][TODAY]["correct"] == 1


# ── 学习页的队列:进度要续得上 ────────────────────────────────────────────────

def test_the_first_session_offers_the_whole_track():
    session = build_session(new_reviews(), TODAY)

    assert len(session) == TRACK_TOTALS["frame"]
    assert session[0]["id"] == FRAMES[0].id


def test_each_track_has_its_own_queue():
    reviews = mark_studied(new_reviews(), FRAMES[0].id, TODAY)

    assert len(build_session(reviews, TODAY, track="frame")) == TRACK_TOTALS["frame"] - 1
    # 在句型里看过一条,不该让搭配那条线少一条。
    assert len(build_session(reviews, TODAY, track="collocation")) == TRACK_TOTALS["collocation"]


def test_a_collocation_question_is_answered_against_its_chinglish_version():
    q = pick_quiz(new_reviews(), TODAY, track="collocation", count=1, rng=_rng())[0]
    answer = PATTERN_BY_ID[q["answer_id"]]

    wrong = next(o for o in q["options"] if o["id"] != q["answer_id"])
    assert wrong["frame"] in answer.wrong
    assert wrong["meaning"] == "直译,英语里不这么说"


def test_an_unknown_track_is_rejected():
    import pytest as _pytest

    with _pytest.raises(ValueError, match="未知的分类"):
        build_session(new_reviews(), TODAY, track="nope")


def test_studied_patterns_drop_out_so_the_next_visit_resumes():
    # 这是"每次打开都从第一条重新学"的那个 bug:看过的条目没有 due 字段,
    # 默认空串比任何日期都小,于是被判成到期、永远排在最前面。
    reviews = new_reviews()
    for pattern in FRAMES[:3]:
        reviews = mark_studied(reviews, pattern.id, TODAY)

    session = build_session(reviews, TODAY)

    assert len(session) == TRACK_TOTALS["frame"] - 3
    assert session[0]["id"] == FRAMES[3].id


def test_a_quizzed_pattern_still_shows_up_until_it_has_been_read():
    # 考过不等于在学习页看过;只有 studied 才让它退出队列。
    reviews = apply_review(new_reviews(), FRAMES[0].id, "instant", TODAY)

    assert build_session(reviews, TODAY)[0]["id"] == FRAMES[0].id


def test_the_session_keeps_the_catalog_order_so_difficulty_still_ramps():
    reviews = mark_studied(new_reviews(), FRAMES[5].id, TODAY)

    levels = [item["level"] for item in build_session(reviews, TODAY)]

    assert levels == sorted(levels, key=["core", "mid", "high"].index)


def test_the_session_is_empty_once_everything_has_been_read():
    reviews = new_reviews()
    for pattern in FRAMES:
        reviews = mark_studied(reviews, pattern.id, TODAY)

    assert build_session(reviews, TODAY) == []


def test_a_pattern_that_is_merely_studied_is_not_treated_as_due_by_the_quiz():
    # 同一个默认值陷阱也在测验里:它会让看过但没考过的条目永远霸占队首。
    reviews = new_reviews()
    for pattern in FRAMES[:30]:
        reviews = mark_studied(reviews, pattern.id, TODAY)
    reviews = apply_review(reviews, FRAMES[50].id, "again", TODAY)  # 真正到期的

    asked = [q["answer_id"] for q in pick_quiz(reviews, TODAY, count=1, rng=_rng())]

    assert asked == [FRAMES[50].id]


def test_each_track_labels_its_groups_in_its_own_terms():
    # 句型按"我现在想干什么"分组,搭配按"我在说哪件事"分组。共用一张表会让
    # turn on the light 顶着「缓和与委婉」的标签。
    frame = next(p for p in PATTERNS_BY_TRACK["frame"] if p.group == "A")
    collocation = next(p for p in PATTERNS_BY_TRACK["collocation"] if p.group == "A")

    assert frame.group_label == "缓和与委婉"
    assert collocation.group_label == "日常起居"
