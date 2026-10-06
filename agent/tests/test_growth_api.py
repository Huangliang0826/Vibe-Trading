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


INTAKE = {
    "chronotype": "early",
    "domains": {
        "dutch": {"level": "zero", "minutes": 10},
        "english": {"level": "read_only", "minutes": 20},
    },
}


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


def test_options_lists_the_two_language_domains_with_tap_choices(client):
    data = client.get("/growth/options").json()

    assert [d["key"] for d in data["domains"]] == ["dutch", "english"]
    assert data["days"] == PLAN_DAYS
    # 每个领域三档起点,全部可点选
    assert all(len(d["levels"]) == 3 for d in data["domains"])


def test_checkin_before_a_plan_exists_is_a_404_not_a_crash(client):
    assert client.post("/growth/checkin", json={"domain": "dutch"}).status_code == 404


# ── 生成计划 ──────────────────────────────────────────────────────────────────

def test_plan_covers_every_requested_domain_for_two_weeks(client):
    data = _plan(client)

    assert set(data["plan"]) == {"dutch", "english"}
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

    assert started == {"configured": False, "generating": True, "ready": 0, "total": 2}


def test_a_second_submit_while_generating_does_not_start_a_second_job(client):
    client.post("/growth/plan", json=INTAKE)

    again = client.post("/growth/plan", json=INTAKE).json()

    assert again["generating"] is True and again["total"] == 2


def test_plan_rejects_a_domain_that_is_no_longer_offered(client):
    bad = {"chronotype": "early", "domains": {"sleep": {"level": "zero", "minutes": 10}}}

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
    assert by_domain["english"]["done"] == 0


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


def test_english_opens_with_the_whole_catalog_and_no_daily_cap(english_client):
    data = english_client.get("/growth/english").json()

    assert data["stats"] == {**data["stats"], "total": 200, "started": 0, "favorites": 0}
    assert data["new_per_day"] is None and data["session_limit"] is None
    assert data["fast_ms"] == 6000
    assert len(data["session"]) == 200
    assert all(item["status"] == "new" for item in data["session"])


def test_the_session_starts_at_the_easiest_level(english_client):
    session = english_client.get("/growth/english").json()["session"]

    assert session[0]["level"] == "core"
    assert [item["level"] for item in session[:100]] == ["core"] * 100


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

    assert len(data["patterns"]) == 200
    assert data["levels"] == [
        {"key": "core", "label": "基础", "total": 100},
        {"key": "mid", "label": "中级", "total": 50},
        {"key": "high", "label": "高级", "total": 50},
    ]
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
