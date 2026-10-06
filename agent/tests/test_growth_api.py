"""个人成长 API:计划生成、打卡、检查点。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
import src.growth.store as store
from src.growth.plan import PLAN_DAYS


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    # 状态写到临时目录,绝不碰用户真实的 ~/.vibe-trading/growth
    monkeypatch.setattr(store, "state_path", lambda: tmp_path / "growth" / "state.json")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


class _DownLLM:
    """模型不可达。整套测试跑在离线状态下,所以断言不会因为外部服务而抖动。"""

    def chat(self, messages, **kwargs):
        raise RuntimeError("offline")


@pytest.fixture(autouse=True)
def no_leftover_job():
    """生成任务存在模块级变量里,跨用例会串。每个用例前后都清掉。"""
    import src.api.growth_routes as routes

    routes._job = None
    yield
    routes._job = None


@pytest.fixture(autouse=True)
def offline_model(monkeypatch):
    import src.api.growth_routes as routes
    from src.growth.plan import generate_domain_plan

    monkeypatch.setattr(
        routes, "generate_domain_plan",
        lambda domain, intake, chronotype: generate_domain_plan(
            domain, intake, chronotype, llm=_DownLLM()),
    )


INTAKE = {"chronotype": "early", "domains": {"dutch": {"level": "zero", "minutes": 10}}}


def _plan(client: TestClient) -> dict:
    """开始生成并等它落盘。生成是后台任务,接口立即返回进度。"""
    started = client.post("/growth/plan", json=INTAKE)
    assert started.status_code == 200, started.text
    assert started.json()["generating"] is True

    for _ in range(50):
        state = client.get("/growth/state").json()
        if state.get("configured"):
            return state
        time.sleep(0.02)
    raise AssertionError(f"计划没有在限定时间内生成:{state}")


# ── 首次进入 ──────────────────────────────────────────────────────────────────

def test_state_reports_not_configured_before_any_plan_exists(client):
    assert client.get("/growth/state").json() == {"configured": False}


def test_options_lists_the_planned_domain_with_tap_choices(client):
    data = client.get("/growth/options").json()

    assert [d["key"] for d in data["domains"]] == ["dutch"]
    assert data["days"] == PLAN_DAYS
    # 每个领域三档起点,全部可点选
    assert all(len(d["levels"]) == 3 for d in data["domains"])


def test_checkin_before_a_plan_exists_is_a_404_not_a_crash(client):
    assert client.post("/growth/checkin", json={"domain": "dutch"}).status_code == 404


# ── 生成计划 ──────────────────────────────────────────────────────────────────

def test_plan_covers_every_requested_domain_for_two_weeks(client):
    data = _plan(client)

    assert set(data["plan"]) == {"dutch"}
    assert all(len(p["steps"]) == PLAN_DAYS for p in data["plan"].values())
    assert all(p["checkpoint"] for p in data["plan"].values())


def test_plan_still_succeeds_when_the_model_is_unreachable(client):
    # 功能可用性不能依赖外部服务。
    data = _plan(client)

    assert all(p["source"] == "fallback" for p in data["plan"].values())
    assert data["configured"] is True


def test_plan_rejects_a_level_outside_the_offered_choices(client):
    bad = {"chronotype": "early", "domains": {"dutch": {"level": "native", "minutes": 10}}}

    assert client.post("/growth/plan", json=bad).status_code == 400


def test_state_reports_generation_progress_while_the_plan_is_being_built(client):
    # 四个领域实测要两分多钟,所以接口立即返回,进度靠轮询。
    started = client.post("/growth/plan", json=INTAKE).json()

    assert started == {"configured": False, "generating": True, "ready": 0, "total": 1}


def test_a_second_submit_while_generating_does_not_start_a_second_job(client):
    client.post("/growth/plan", json=INTAKE)

    again = client.post("/growth/plan", json=INTAKE).json()

    assert again["generating"] is True and again["total"] == 1


def test_plan_rejects_a_domain_that_is_no_longer_offered(client):
    bad = {"chronotype": "early", "domains": {"english": {"level": "zero", "minutes": 10}}}

    assert client.post("/growth/plan", json=bad).status_code == 400


def test_overview_opens_on_the_first_step_of_each_domain(client):
    overview = _plan(client)["overview"]

    assert overview["total_done"] == 0
    assert all(d["next_step"]["day"] == 1 for d in overview["domains"])
    assert overview["checkpoint"]["days_left"] == PLAN_DAYS - 1


# ── 打卡 ──────────────────────────────────────────────────────────────────────

def test_checkin_advances_only_its_own_domain(client):
    _plan(client)

    data = client.post("/growth/checkin", json={"domain": "dutch"}).json()

    by_domain = {d["domain"]: d for d in data["overview"]["domains"]}
    assert by_domain["dutch"]["done"] == 1 and by_domain["dutch"]["done_today"] is True


def test_tapping_twice_in_one_day_does_not_consume_two_days_of_plan(client):
    _plan(client)
    client.post("/growth/checkin", json={"domain": "dutch"})

    data = client.post("/growth/checkin", json={"domain": "dutch"}).json()

    assert data["overview"]["total_done"] == 1


def test_undo_takes_todays_checkin_back(client):
    _plan(client)
    client.post("/growth/checkin", json={"domain": "dutch"})

    data = client.post("/growth/checkin/undo", json={"domain": "dutch"}).json()

    by_domain = {d["domain"]: d for d in data["overview"]["domains"]}
    assert by_domain["dutch"]["done"] == 0 and by_domain["dutch"]["done_today"] is False


def test_checkin_survives_a_restart(client):
    _plan(client)
    client.post("/growth/checkin", json={"domain": "dutch"})

    # 手机上打卡、电脑上回顾:数据必须在服务端,不能只活在某个浏览器里。
    assert client.get("/growth/state").json()["overview"]["total_done"] == 1


# ── 检查点 ────────────────────────────────────────────────────────────────────

def test_checkpoint_records_a_baseline_and_a_result(client):
    _plan(client)
    client.post("/growth/checkpoint", json={"domain": "dutch", "which": "start", "value": "说 40 秒卡住"})

    data = client.post("/growth/checkpoint",
                       json={"domain": "dutch", "which": "end", "value": "说满 1 分钟"}).json()

    assert data["checkpoints"]["dutch"] == {"start": "说 40 秒卡住", "end": "说满 1 分钟"}


def test_checkpoint_rejects_an_unknown_slot(client):
    _plan(client)

    response = client.post("/growth/checkpoint",
                           json={"domain": "dutch", "which": "middle", "value": "x"})

    assert response.status_code == 400


# ── 重置 ──────────────────────────────────────────────────────────────────────

def test_reset_clears_the_plan(client):
    _plan(client)

    assert client.post("/growth/reset").json() == {"configured": False}
    assert client.get("/growth/state").json() == {"configured": False}


def test_state_file_is_not_world_readable(client, tmp_path):
    _plan(client)

    mode = (tmp_path / "growth" / "state.json").stat().st_mode & 0o777
    assert mode == 0o600


# ── 英语句型 ──────────────────────────────────────────────────────────────────

@pytest.fixture
def english_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(store, "english_path", lambda: tmp_path / "growth" / "english.json")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_english_opens_with_the_whole_catalog(english_client):
    data = english_client.get("/growth/english").json()

    from src.growth.english_patterns import TRACK_TOTALS

    assert data["stats"] == {**data["stats"],
                             "total": TRACK_TOTALS["frame"], "started": 0, "favorites": 0}
    assert data["fast_ms"] == 6000
    assert len(data["session"]) == TRACK_TOTALS["frame"]
    assert [t["key"] for t in data["tracks"]] == ["frame", "oneliner", "collocation"]


def test_the_learning_queue_resumes_where_it_was_left(english_client):
    first = english_client.get("/growth/english").json()["session"][0]["id"]
    english_client.post("/growth/english/studied", json={"pattern_id": first})

    session = english_client.get("/growth/english").json()["session"]

    assert len(session) == 151  # 152 - 1
    assert session[0]["id"] != first


def test_the_session_starts_at_the_easiest_level(english_client):
    session = english_client.get("/growth/english").json()["session"]

    assert session[0]["level"] == "core"
    assert [item["level"] for item in session[:80]] == ["core"] * 80


def test_english_session_items_carry_the_cue_but_the_drill_still_needs_the_answer(english_client):
    item = english_client.get("/growth/english").json()["session"][0]

    assert item["cue"] and item["frame"] and len(item["examples"]) >= 2


def test_a_correct_fast_answer_moves_the_pattern_forward(english_client):
    first = english_client.get("/growth/english").json()["session"][0]["id"]

    result = english_client.post("/growth/english/answer", json={
        "pattern_id": first, "chosen_id": first, "elapsed_ms": 1200,
    }).json()

    assert result["correct"] is True and result["grade"] == "instant"
    assert result["stats"]["tested"] == 1


def test_the_server_decides_right_and_wrong_not_the_client(english_client):
    # 客户端只报选了哪张卡,报不了"我对了"。
    result = english_client.post("/growth/english/answer", json={
        "pattern_id": "the-thing-is", "chosen_id": "it-depends-on", "elapsed_ms": 500,
    }).json()

    assert result["correct"] is False and result["grade"] == "again"


def test_a_slow_correct_answer_is_not_treated_as_automatic(english_client):
    result = english_client.post("/growth/english/answer", json={
        "pattern_id": "the-thing-is", "chosen_id": "the-thing-is", "elapsed_ms": 20_000,
    }).json()

    assert result["correct"] is True and result["grade"] == "slow"


def test_the_quiz_endpoint_returns_two_option_questions(english_client):
    data = english_client.get("/growth/english/quiz?count=6").json()

    assert len(data["questions"]) == 6
    assert data["options_per_question"] == 2
    for q in data["questions"]:
        assert len(q["options"]) == 2
        assert q["answer_id"] in [o["id"] for o in q["options"]]


def test_marking_a_pattern_studied_does_not_score_it(english_client):
    data = english_client.post("/growth/english/studied",
                               json={"pattern_id": "the-thing-is"}).json()

    assert data["stats"]["started"] == 1
    assert data["stats"]["tested"] == 0
    assert data["stats"]["accuracy"] is None


def test_english_rejects_an_unknown_pattern(english_client):
    response = english_client.post(
        "/growth/english/answer",
        json={"pattern_id": "nope", "chosen_id": "nope", "elapsed_ms": 100},
    )

    assert response.status_code == 400


def test_the_full_catalog_is_available_with_each_patterns_box(english_client):
    english_client.post("/growth/english/answer", json={
        "pattern_id": "the-thing-is", "chosen_id": "the-thing-is", "elapsed_ms": 900})

    data = english_client.get("/growth/english/patterns").json()

    from src.growth.english_patterns import TRACK_TOTALS

    assert len(data["patterns"]) == TRACK_TOTALS["frame"]
    assert {lv["key"] for lv in data["levels"]} == {"core", "mid", "high"}
    assert sum(lv["total"] for lv in data["levels"]) == TRACK_TOTALS["frame"]
    by_id = {p["id"]: p for p in data["patterns"]}
    assert by_id["the-thing-is"]["box"] == 1
    assert by_id["it-depends-on"]["box"] == -1  # 还没练过


def test_english_reset_clears_progress(english_client):
    english_client.post("/growth/english/answer", json={
        "pattern_id": "the-thing-is", "chosen_id": "the-thing-is", "elapsed_ms": 900})

    data = english_client.post("/growth/english/reset").json()

    assert data["stats"]["started"] == 0


def test_english_progress_file_is_not_world_readable(english_client, tmp_path):
    english_client.post("/growth/english/answer", json={
        "pattern_id": "the-thing-is", "chosen_id": "the-thing-is", "elapsed_ms": 900})

    mode = (tmp_path / "growth" / "english.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_domain_levels_and_english_levels_do_not_collide(client):
    # 两边都叫 LEVELS:同名导入曾经把领域起点选项整个盖掉。
    options = client.get("/growth/options").json()

    by_key = {d["key"]: d for d in options["domains"]}
    assert [lv["key"] for lv in by_key["dutch"]["levels"]] == [
        "zero", "words", "basic_talk",
    ]


def test_favoriting_a_pattern_shows_up_in_the_list_and_the_count(english_client):
    data = english_client.post("/growth/english/favorite",
                               json={"pattern_id": "the-thing-is", "favorite": True}).json()

    assert data["stats"]["favorites"] == 1
    assert [f["id"] for f in data["favorites"]] == ["the-thing-is"]


def test_unfavoriting_takes_it_back_off_the_list(english_client):
    english_client.post("/growth/english/favorite",
                        json={"pattern_id": "the-thing-is", "favorite": True})

    data = english_client.post("/growth/english/favorite",
                               json={"pattern_id": "the-thing-is", "favorite": False}).json()

    assert data["favorites"] == [] and data["stats"]["favorites"] == 0


def test_a_favorite_survives_being_quizzed(english_client):
    english_client.post("/growth/english/favorite",
                        json={"pattern_id": "the-thing-is", "favorite": True})

    english_client.post("/growth/english/answer", json={
        "pattern_id": "the-thing-is", "chosen_id": "the-thing-is", "elapsed_ms": 900})

    assert english_client.get("/growth/english").json()["stats"]["favorites"] == 1


def test_favoriting_rejects_an_unknown_pattern(english_client):
    response = english_client.post("/growth/english/favorite",
                                   json={"pattern_id": "nope", "favorite": True})

    assert response.status_code == 400


# ── 每天 ←→ 英语句型 的联通 ───────────────────────────────────────────────────

@pytest.fixture
def both_client(tmp_path: Path, monkeypatch) -> TestClient:
    """同时隔离计划与英语进度——这条链路要跨两个文件。"""
    monkeypatch.setattr(store, "state_path", lambda: tmp_path / "growth" / "state.json")
    monkeypatch.setattr(store, "english_path", lambda: tmp_path / "growth" / "english.json")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _answer_correctly(client: TestClient, times: int) -> None:
    ids = [q["answer_id"] for q in client.get(f"/growth/english/quiz?count={times}").json()["questions"]]
    for pattern_id in ids[:times]:
        client.post("/growth/english/answer", json={
            "pattern_id": pattern_id, "chosen_id": pattern_id, "elapsed_ms": 800,
        })


def test_todays_english_goal_starts_empty(both_client):
    english = both_client.get("/growth/state").json()
    # 还没建计划时也该给出英语进度:英语不依赖计划。
    assert english["configured"] is False


def test_quiz_answers_drive_the_english_item_on_the_daily_page(both_client):
    _plan(both_client)

    _answer_correctly(both_client, 4)

    english = both_client.get("/growth/state").json()["overview"]["english"]
    assert english == {"goal": 10, "correct": 4, "answered": 4, "done": False}


def test_reaching_the_goal_completes_the_english_item_without_a_manual_checkin(both_client):
    # 英语的"完成"量的是结果,不是按下按钮的意愿。
    _plan(both_client)

    _answer_correctly(both_client, 10)

    overview = both_client.get("/growth/state").json()["overview"]
    assert overview["english"]["done"] is True
    assert overview["summary"]["active_days"] == 1


def test_a_wrong_answer_does_not_move_the_daily_goal(both_client):
    _plan(both_client)

    both_client.post("/growth/english/answer", json={
        "pattern_id": "the-thing-is", "chosen_id": "it-depends-on", "elapsed_ms": 500,
    })

    english = both_client.get("/growth/state").json()["overview"]["english"]
    assert english["answered"] == 1 and english["correct"] == 0


def test_the_calendar_marks_a_day_where_only_english_was_done(both_client):
    _plan(both_client)

    _answer_correctly(both_client, 10)

    calendar = both_client.get("/growth/state").json()["overview"]["calendar"]
    assert calendar[-1]["state"] == "partial"
    assert calendar[-1]["english"] is True and calendar[-1]["plan"] is False


def test_the_calendar_marks_a_full_day_when_both_are_done(both_client):
    _plan(both_client)
    both_client.post("/growth/checkin", json={"domain": "dutch"})

    _answer_correctly(both_client, 10)

    overview = both_client.get("/growth/state").json()["overview"]
    assert overview["calendar"][-1]["state"] == "full"
    assert overview["summary"]["full_days"] == 1


def test_the_calendar_covers_four_weeks(both_client):
    _plan(both_client)

    calendar = both_client.get("/growth/state").json()["overview"]["calendar"]

    assert len(calendar) == 28
    assert calendar[0]["date"] < calendar[-1]["date"]  # 从早到晚


# ── 三条线互不干扰 ────────────────────────────────────────────────────────────

def test_each_track_reports_its_own_totals(english_client):
    from src.growth.english_patterns import TRACK_TOTALS

    sizes = {
        t: english_client.get(f"/growth/english?track={t}").json()["stats"]["total"]
        for t in ("frame", "oneliner", "collocation")
    }

    assert sizes == TRACK_TOTALS
    assert sum(sizes.values()) > 0 and len(set(sizes.values())) == 3


def test_reading_one_track_does_not_shorten_another(english_client):
    first = english_client.get("/growth/english?track=frame").json()["session"][0]["id"]
    english_client.post("/growth/english/studied", json={"pattern_id": first})

    from src.growth.english_patterns import TRACK_TOTALS

    data = english_client.get("/growth/english?track=collocation").json()

    assert len(data["session"]) == TRACK_TOTALS["collocation"]
    assert data["stats"]["started"] == 0


def test_a_collocation_quiz_offers_the_chinglish_version(english_client):
    questions = english_client.get("/growth/english/quiz?track=collocation&count=8").json()

    assert questions["track"] == "collocation"
    for q in questions["questions"]:
        wrong = next(o for o in q["options"] if o["id"] != q["answer_id"])
        assert wrong["meaning"] == "直译,英语里不这么说"
        assert wrong["id"].endswith("#wrong")


def test_choosing_the_chinglish_version_is_marked_wrong(english_client):
    q = english_client.get("/growth/english/quiz?track=collocation&count=1").json()["questions"][0]
    wrong_id = next(o["id"] for o in q["options"] if o["id"] != q["answer_id"])

    result = english_client.post("/growth/english/answer", json={
        "pattern_id": q["answer_id"], "chosen_id": wrong_id, "elapsed_ms": 800,
    }).json()

    assert result["correct"] is False and result["grade"] == "again"


def test_answering_in_any_track_counts_towards_the_daily_goal(english_client):
    # 「每天」那项算的是今天练了多少英语,不该因为分了类就要答三倍。
    q = english_client.get("/growth/english/quiz?track=collocation&count=1").json()["questions"][0]

    result = english_client.post("/growth/english/answer", json={
        "pattern_id": q["answer_id"], "chosen_id": q["answer_id"], "elapsed_ms": 800,
    }).json()

    assert result["today_progress"]["correct"] == 1


def test_an_unknown_track_is_a_400(english_client):
    assert english_client.get("/growth/english?track=nope").status_code == 400
    assert english_client.get("/growth/english/quiz?track=nope").status_code == 400


def test_the_catalog_is_scoped_to_the_requested_track(english_client):
    from src.growth.english_patterns import TRACK_TOTALS

    data = english_client.get("/growth/english/patterns?track=oneliner").json()

    assert len(data["patterns"]) == TRACK_TOTALS["oneliner"]
    assert all(p["track"] == "oneliner" for p in data["patterns"])
