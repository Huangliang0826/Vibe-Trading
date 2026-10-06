"""英语句型:内容清单与间隔重复逻辑。"""

import pytest

from src.growth.english import (
    MAX_BOX, apply_review, build_session, introduced_today,
    new_reviews, shaky, stats,
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


def test_the_cue_never_gives_the_answer_away():
    # 提示里若混入英文,检索练习就退化成朗读。
    for p in PATTERNS:
        assert not any(ch.isascii() and ch.isalpha() for ch in p.cue), (p.id, p.cue)


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
