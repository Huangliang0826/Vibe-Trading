"""个人成长:进度推导与状态转换。"""
import pytest

from src.growth.plan import PLAN_DAYS, fallback_plan
from src.growth.progress import (
    build_overview, domain_progress, missed_two_days, streak,
)
from src.growth.store import apply_checkin, new_state, set_checkpoint, undo_checkin


def _state(today="2026-10-05", domains=("dutch", "english")):
    plan = {d: fallback_plan(d, 10) for d in domains}
    intake = {d: {"level": "zero" if d == "dutch" else "read_only", "minutes": 10} for d in domains}
    return new_state(plan=plan, intake=intake, chronotype="early", today=today)


# ── 推进按"做到第几步",不按日历 ───────────────────────────────────────────────

def test_progress_starts_at_the_first_step():
    p = domain_progress("dutch", fallback_plan("dutch", 10), [], "2026-10-05")

    assert p.done == 0 and p.next_step["day"] == 1
    assert p.dots[0] == "next" and len(p.dots) == PLAN_DAYS


def test_missing_days_shifts_the_plan_instead_of_skipping_content():
    # 第 1 天做了,之后空了一周。下一步仍然是第 2 天,而不是按日历跳到第 8 天。
    checkins = [{"date": "2026-10-05", "domain": "dutch", "day": 1}]

    p = domain_progress("dutch", fallback_plan("dutch", 10), checkins, "2026-10-13")

    assert p.done == 1 and p.next_step["day"] == 2


def test_progress_reports_completion_when_every_step_is_done():
    checkins = [{"date": f"2026-10-{5 + i:02d}", "domain": "dutch", "day": i + 1}
                for i in range(PLAN_DAYS)]

    p = domain_progress("dutch", fallback_plan("dutch", 10), checkins, "2026-10-19")

    assert p.done == PLAN_DAYS and p.next_step is None and p.percent == 100
    assert "todo" not in p.dots and "next" not in p.dots


def test_progress_only_counts_its_own_domain():
    checkins = [{"date": "2026-10-05", "domain": "english", "day": 1}]

    p = domain_progress("dutch", fallback_plan("dutch", 10), checkins, "2026-10-05")

    assert p.done == 0


# ── 连续天数 ──────────────────────────────────────────────────────────────────

def test_streak_counts_back_from_yesterday_before_today_is_logged():
    # 早上一打开就看到 0,是在为还没发生的事惩罚人。
    checkins = [{"date": "2026-10-03", "domain": "dutch"}, {"date": "2026-10-04", "domain": "dutch"}]

    assert streak(checkins, "2026-10-05") == 2


def test_streak_includes_today_once_logged():
    checkins = [{"date": d, "domain": "dutch"} for d in ("2026-10-03", "2026-10-04", "2026-10-05")]

    assert streak(checkins, "2026-10-05") == 3


def test_streak_breaks_after_two_silent_days():
    checkins = [{"date": "2026-10-01", "domain": "dutch"}]

    assert streak(checkins, "2026-10-05") == 0


def test_one_missed_day_is_not_nudged_but_two_are():
    one = [{"date": "2026-10-04", "domain": "dutch"}]
    two = [{"date": "2026-10-02", "domain": "dutch"}]

    assert missed_two_days(one, "2026-10-05") is False
    assert missed_two_days(two, "2026-10-05") is True


# ── 状态转换 ──────────────────────────────────────────────────────────────────

def test_checkin_advances_one_step():
    state = apply_checkin(_state(), domain="dutch", today="2026-10-05")

    assert len(state["checkins"]) == 1
    assert state["checkins"][0]["day"] == 1


def test_a_second_tap_on_the_same_day_does_not_advance_two_steps():
    # 手机上的误触不该把当天内容悄悄跳过去。
    state = apply_checkin(_state(), domain="dutch", today="2026-10-05")
    state = apply_checkin(state, domain="dutch", today="2026-10-05")

    assert len(state["checkins"]) == 1


def test_checkin_stops_at_the_end_of_the_plan():
    state = _state()
    for i in range(PLAN_DAYS + 3):
        state = apply_checkin(state, domain="dutch", today=f"2026-11-{i + 1:02d}")

    assert len(state["checkins"]) == PLAN_DAYS


def test_checkin_rejects_a_domain_the_plan_does_not_cover():
    with pytest.raises(ValueError, match="计划里没有"):
        apply_checkin(_state(domains=("dutch",)), domain="english", today="2026-10-05")


def test_undo_removes_only_todays_entry_for_that_domain():
    state = _state()
    state = apply_checkin(state, domain="dutch", today="2026-10-04")
    state = apply_checkin(state, domain="dutch", today="2026-10-05")
    state = apply_checkin(state, domain="english", today="2026-10-05")

    state = undo_checkin(state, domain="dutch", today="2026-10-05")

    remaining = [(c["domain"], c["date"]) for c in state["checkins"]]
    assert remaining == [("dutch", "2026-10-04"), ("english", "2026-10-05")]


def test_checkpoint_keeps_the_baseline_when_the_result_is_recorded():
    state = set_checkpoint(_state(), domain="dutch", which="start", value="说 40 秒就卡住")
    state = set_checkpoint(state, domain="dutch", which="end", value="说满 1 分钟")

    assert state["checkpoints"]["dutch"] == {"start": "说 40 秒就卡住", "end": "说满 1 分钟"}


def test_checkpoint_rejects_an_unknown_slot():
    with pytest.raises(ValueError, match="start 或 end"):
        set_checkpoint(_state(), domain="dutch", which="middle", value="x")


# ── 总览 ──────────────────────────────────────────────────────────────────────

def test_overview_reports_the_two_week_due_date_and_days_left():
    overview = build_overview(_state(today="2026-10-05"), "2026-10-05")

    assert overview["checkpoint"]["due_date"] == "2026-10-18"
    assert overview["checkpoint"]["days_left"] == 13
    assert overview["checkpoint"]["due"] is False


def test_overview_marks_the_checkpoint_due_at_two_weeks():
    overview = build_overview(_state(today="2026-10-05"), "2026-10-18")

    assert overview["checkpoint"]["due"] is True and overview["checkpoint"]["days_left"] == 0


def test_overview_counts_how_many_domains_are_already_done_today():
    state = apply_checkin(_state(), domain="dutch", today="2026-10-05")

    overview = build_overview(state, "2026-10-05")

    assert overview["done_today"] == 1 and overview["domain_count"] == 2
    assert overview["total_steps"] == PLAN_DAYS * 2 and overview["total_done"] == 1


def test_a_brand_new_plan_is_not_scolded_for_breaking_a_streak():
    # 刚建完计划、当天打了卡,却被提示"断了两天"——这是最早的两条打卡数据
    # 必然触发的误报。
    state = apply_checkin(_state(today="2026-10-05"), domain="dutch", today="2026-10-05")

    assert build_overview(state, "2026-10-05")["nudge"] is False


def test_nudge_stays_quiet_on_a_day_that_has_been_logged():
    checkins = [{"date": "2026-10-01", "domain": "dutch"}, {"date": "2026-10-05", "domain": "dutch"}]

    assert missed_two_days(checkins, "2026-10-05") is False


def test_the_card_shows_what_was_finished_today_not_tomorrows_step():
    # 打完卡后把"今天完成"贴在明天的动作上,会让人以为做错了内容。
    state = apply_checkin(_state(), domain="dutch", today="2026-10-05")

    dutch = next(d for d in build_overview(state, "2026-10-05")["domains"] if d["domain"] == "dutch")

    assert dutch["today_step"]["day"] == 1
    assert dutch["next_step"]["day"] == 2


def test_there_is_no_today_step_before_the_first_checkin():
    dutch = next(d for d in build_overview(_state(), "2026-10-05")["domains"] if d["domain"] == "dutch")

    assert dutch["today_step"] is None


def test_an_older_plan_with_retired_domains_still_opens():
    # 睡眠和健身去掉之前生成的计划不该变成一堵墙,只显示还支持的领域就好。
    state = _state(domains=("dutch",))
    state["plan"]["sleep"] = fallback_plan("dutch", 10)  # 冒充一个已退役的领域

    overview = build_overview(state, "2026-10-06")

    assert [d["domain"] for d in overview["domains"]] == ["dutch"]


def test_domains_are_shown_in_a_fixed_order():
    overview = build_overview(_state(domains=("english", "dutch")), "2026-10-06")

    assert [d["domain"] for d in overview["domains"]] == ["dutch", "english"]
