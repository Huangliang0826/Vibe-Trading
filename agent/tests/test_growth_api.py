"""个人成长 API:每天的目标、两门语言的练习、打卡日历。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
import src.growth.store as store
from src.growth.dutch_patterns import DUTCH
from src.growth.english_patterns import ENGLISH


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    # 两门语言各一个文件,全部隔离到临时目录。
    monkeypatch.setattr(store, "state_path", lambda lang: tmp_path / f"{lang}.json")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _answer(client: TestClient, lang: str, track: str, times: int, correct: bool = True):
    ids = [q["answer_id"] for q in
           client.get(f"/growth/practice/quiz?lang={lang}&track={track}&count={times}")
           .json()["questions"]]
    for pattern_id in ids[:times]:
        client.post("/growth/practice/answer", json={
            "pattern_id": pattern_id,
            "chosen_id": pattern_id if correct else "nope",
            "elapsed_ms": 800,
        })
    return ids[:times]


# ── 每天 ──────────────────────────────────────────────────────────────────────

def test_the_daily_page_opens_with_both_languages_and_no_setup(client):
    # 计划没了,也就没有"还没配置"这回事:打开就能用。
    data = client.get("/growth/state").json()

    assert [lang["key"] for lang in data["languages"]] == ["en", "nl"]
    assert data["done_today"] == 0 and data["lang_count"] == 2
    assert len(data["calendar"]) == 28


def test_each_language_carries_its_own_goal(client):
    goals = {lang["key"]: lang["goal"] for lang in client.get("/growth/state").json()["languages"]}

    # 荷兰语零基础起步,门槛定得低一些。
    assert goals == {"en": 10, "nl": 6}


def test_answering_dutch_moves_only_the_dutch_item(client):
    _answer(client, "nl", "oneliner", 3)

    by_key = {lang["key"]: lang for lang in client.get("/growth/state").json()["languages"]}
    assert by_key["nl"]["correct"] == 3 and by_key["nl"]["done"] is False
    assert by_key["en"]["correct"] == 0


def test_reaching_a_goal_completes_that_language_without_a_manual_checkin(client):
    _answer(client, "nl", "oneliner", 6)

    data = client.get("/growth/state").json()
    by_key = {lang["key"]: lang for lang in data["languages"]}
    assert by_key["nl"]["done"] is True
    assert data["done_today"] == 1
    assert data["calendar"][-1]["state"] == "partial"


def test_the_calendar_fills_in_when_both_languages_are_done(client):
    _answer(client, "nl", "oneliner", 6)
    _answer(client, "en", "frame", 10)

    data = client.get("/growth/state").json()
    assert data["calendar"][-1]["state"] == "full"
    assert data["summary"]["full_days"] == 1 and data["done_today"] == 2


def test_a_wrong_answer_does_not_count_towards_the_goal(client):
    _answer(client, "nl", "oneliner", 3, correct=False)

    by_key = {lang["key"]: lang for lang in client.get("/growth/state").json()["languages"]}
    assert by_key["nl"]["answered"] == 3 and by_key["nl"]["correct"] == 0


# ── 练习 ──────────────────────────────────────────────────────────────────────

def test_english_offers_three_tracks_and_dutch_two(client):
    english = client.get("/growth/practice?lang=en").json()
    dutch = client.get("/growth/practice?lang=nl").json()

    assert [t["key"] for t in english["tracks"]] == ["frame", "oneliner", "collocation"]
    # 零基础阶段用不上话语框架,所以荷兰语没有句型。
    assert [t["key"] for t in dutch["tracks"]] == ["oneliner", "collocation"]


def test_each_language_defaults_to_its_own_first_track(client):
    assert client.get("/growth/practice?lang=en").json()["track"] == "frame"
    assert client.get("/growth/practice?lang=nl").json()["track"] == "oneliner"


def test_track_totals_match_the_catalog(client):
    for lang, cat in (("en", ENGLISH), ("nl", DUTCH)):
        for track, total in cat.track_totals.items():
            data = client.get(f"/growth/practice?lang={lang}&track={track}").json()
            assert data["stats"]["total"] == total
            assert len(data["session"]) == total


def test_studying_one_language_does_not_touch_the_other(client):
    first = client.get("/growth/practice?lang=en").json()["session"][0]["id"]
    client.post("/growth/practice/studied", json={"pattern_id": first})

    dutch = client.get("/growth/practice?lang=nl").json()
    assert dutch["stats"]["started"] == 0
    assert len(dutch["session"]) == DUTCH.track_totals["oneliner"]


def test_the_learning_queue_resumes_where_it_was_left(client):
    first = client.get("/growth/practice?lang=nl").json()["session"][0]["id"]
    client.post("/growth/practice/studied", json={"pattern_id": first})

    session = client.get("/growth/practice?lang=nl").json()["session"]

    assert len(session) == DUTCH.track_totals["oneliner"] - 1
    assert session[0]["id"] != first


def test_a_dutch_collocation_quiz_offers_a_literal_translation(client):
    data = client.get("/growth/practice/quiz?lang=nl&track=collocation&count=6").json()

    assert data["lang"] == "nl"
    for q in data["questions"]:
        wrong = next(o for o in q["options"] if o["id"] != q["answer_id"])
        assert wrong["meaning"] == "直译,英语里不这么说"


def test_the_server_decides_right_and_wrong(client):
    result = client.post("/growth/practice/answer", json={
        "pattern_id": "nl-dat-klopt", "chosen_id": "nl-prima", "elapsed_ms": 500,
    }).json()

    assert result["correct"] is False and result["grade"] == "again"


def test_a_slow_correct_answer_is_not_treated_as_automatic(client):
    result = client.post("/growth/practice/answer", json={
        "pattern_id": "nl-dat-klopt", "chosen_id": "nl-dat-klopt", "elapsed_ms": 20_000,
    }).json()

    assert result["correct"] is True and result["grade"] == "slow"


def test_favourites_are_scoped_to_their_own_language_and_track(client):
    client.post("/growth/practice/favorite",
                json={"pattern_id": "nl-dat-klopt", "favorite": True})

    dutch = client.get("/growth/practice?lang=nl&track=oneliner").json()
    english = client.get("/growth/practice?lang=en&track=frame").json()

    assert [f["id"] for f in dutch["favorites"]] == ["nl-dat-klopt"]
    assert english["favorites"] == []


def test_an_id_operation_infers_its_language(client):
    # 按 id 操作的端点不带语言参数,返回体仍要是这条内容所属语言的进度。
    data = client.post("/growth/practice/studied", json={"pattern_id": "nl-prima"}).json()

    assert data["lang"] == "nl" and data["track"] == "oneliner"


def test_the_catalog_is_scoped_to_the_requested_track(client):
    data = client.get("/growth/practice/catalog?lang=nl&track=collocation").json()

    assert len(data["patterns"]) == DUTCH.track_totals["collocation"]
    assert all(p["lang"] == "nl" for p in data["patterns"])


def test_reset_clears_only_that_language(client):
    _answer(client, "nl", "oneliner", 2)
    _answer(client, "en", "frame", 2)

    client.post("/growth/practice/reset?lang=nl")

    assert client.get("/growth/practice?lang=nl").json()["stats"]["tested"] == 0
    assert client.get("/growth/practice?lang=en").json()["stats"]["tested"] == 2


def test_unknown_language_or_track_is_a_400(client):
    assert client.get("/growth/practice?lang=de").status_code == 400
    assert client.get("/growth/practice?lang=nl&track=frame").status_code == 400


def test_state_files_are_not_world_readable(client, tmp_path):
    _answer(client, "nl", "oneliner", 1)

    assert (tmp_path / "nl.json").stat().st_mode & 0o777 == 0o600
