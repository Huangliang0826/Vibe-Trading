"""Tests for AI 动态出题 route (learning/generate-quiz)."""

import json
import random

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import learning_routes
from src.api.learning_routes import (
    GenerateQuizRequest,
    _extract_quiz_json,
    _validate_and_shuffle,
    register_learning_routes,
)


def test_extract_quiz_json_plain():
    obj = _extract_quiz_json('{"type": "choice", "question": "q"}')
    assert obj["type"] == "choice"


def test_extract_quiz_json_with_code_fence():
    text = "```json\n{\"question\": \"q\", \"answer\": 1}\n```"
    assert _extract_quiz_json(text)["answer"] == 1


def test_extract_quiz_json_with_surrounding_prose():
    text = "好的,这是题目:\n{\"question\": \"q\"}\n希望有帮助"
    assert _extract_quiz_json(text)["question"] == "q"


def test_extract_quiz_json_empty_raises():
    with pytest.raises(ValueError):
        _extract_quiz_json("   ")


def test_validate_and_shuffle_preserves_correct_answer():
    raw = {
        "type": "scenario",
        "question": "情景题?",
        "options": ["A", "B", "C", "D"],
        "answer": 2,  # "C"
        "explanation": "因为 C 对",
    }
    # 固定随机种子让洗牌可复现
    quiz = _validate_and_shuffle(raw, rng=random.Random(0))
    assert quiz.type == "scenario"
    assert set(quiz.options) == {"A", "B", "C", "D"}
    # 洗牌后 answer 下标仍指向原正确项 "C"
    assert quiz.options[quiz.answer] == "C"
    assert quiz.ai_generated is True


def test_validate_rejects_bad_answer_index():
    with pytest.raises(ValueError):
        _validate_and_shuffle(
            {"question": "q", "options": ["a", "b"], "answer": 5, "explanation": "e"}
        )


def test_validate_rejects_missing_explanation():
    with pytest.raises(ValueError):
        _validate_and_shuffle(
            {"question": "q", "options": ["a", "b"], "answer": 0, "explanation": ""}
        )


def test_validate_unknown_type_falls_back_to_choice():
    quiz = _validate_and_shuffle(
        {"type": "essay", "question": "q", "options": ["a", "b"], "answer": 0, "explanation": "e"},
        rng=random.Random(1),
    )
    assert quiz.type == "choice"


def test_route_returns_generated_quiz(monkeypatch):
    """端到端:mock 掉 DeepSeek 调用,验证路由解析并返回题目。"""
    payload = {
        "type": "judge",
        "question": "这句话对吗?",
        "options": ["对", "错", "无法判断", "以上都不是"],
        "answer": 1,
        "explanation": "解析文本",
    }
    monkeypatch.setattr(learning_routes, "_call_deepseek", lambda *a, **k: json.dumps(payload))

    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    resp = TestClient(app).post(
        "/learning/generate-quiz",
        json={"topic_title": "风险管理", "title": "止损", "core": "止损是..."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai_generated"] is True
    assert data["options"][data["answer"]] == "错"
    assert data["type"] == "judge"


def test_route_503_when_model_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(learning_routes, "_call_deepseek", boom)
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    resp = TestClient(app).post(
        "/learning/generate-quiz",
        json={"topic_title": "t", "title": "x", "core": "c"},
    )
    assert resp.status_code == 503


def test_route_503_when_no_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def real_call(*a, **k):
        # 复用真实实现以触发缺 key 的 503
        return learning_routes._call_deepseek(*a, **k)

    monkeypatch.setattr(learning_routes, "_call_deepseek", real_call)
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    resp = TestClient(app).post(
        "/learning/generate-quiz",
        json={"topic_title": "t", "title": "x", "core": "c"},
    )
    assert resp.status_code == 503


def test_request_model_length_guard():
    with pytest.raises(Exception):
        GenerateQuizRequest(topic_title="t", title="x", core="c" * 5000)


# ── 知识点扩充(generate-cards)────────────────────────────────────────────

from src.api.learning_routes import (  # noqa: E402
    GenerateCardsRequest,
    _CARD_CHUNK,
    _validate_card,
)


def _good_card(title="新知识点"):
    return {
        "type": "story",
        "difficulty": 2,
        "title": title,
        "core": "核心讲解内容,足够长。",
        "example": "一个真实市场案例。",
        "pitfall": "很多人以为 X,其实 Y。",
        "quiz": {
            "type": "scenario",
            "question": "情景题?",
            "options": ["对的做法", "错法一", "错法二", "错法三"],
            "answer": 0,
            "explanation": "因为对的做法符合原则。",
        },
    }


def test_validate_card_ok():
    card = _validate_card(_good_card(), set(), random.Random(0))
    assert card.type == "story"
    assert card.difficulty == 2
    assert card.quiz.options[card.quiz.answer] == "对的做法"


def test_validate_card_rejects_duplicate_title():
    with pytest.raises(ValueError):
        _validate_card(_good_card("已存在"), {"已存在"}, random.Random(0))


def test_validate_card_normalizes_bad_difficulty_and_type():
    raw = _good_card()
    raw["difficulty"] = 9
    raw["type"] = "unknown"
    card = _validate_card(raw, set(), random.Random(0))
    assert card.difficulty == 2
    assert card.type == "concept"


def test_generate_cards_route(monkeypatch):
    # count <= chunk size 走单块路径
    batch = {"cards": [_good_card(f"知识点{i}") for i in range(6)]}
    monkeypatch.setattr(learning_routes, "_call_deepseek", lambda *a, **k: json.dumps(batch))
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    resp = TestClient(app).post(
        "/learning/generate-cards",
        json={"topic_id": "market", "topic_title": "市场与交易机制", "count": 4},
    )
    assert resp.status_code == 200
    cards = resp.json()["cards"]
    assert len(cards) == 4
    assert all(c["quiz"]["options"][c["quiz"]["answer"]] == "对的做法" for c in cards)


def test_generate_cards_route_parallel_merges_to_target(monkeypatch):
    """count>chunk 时并行分块生成,合并去重后达到目标数量。"""
    import itertools
    import threading

    counter = itertools.count()
    lock = threading.Lock()

    def distinct_cards(*a, **k):
        with lock:
            base = next(counter)
        return json.dumps({"cards": [_good_card(f"P{base}-{i}") for i in range(_CARD_CHUNK)]})

    monkeypatch.setattr(learning_routes, "_call_deepseek", distinct_cards)
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    resp = TestClient(app).post(
        "/learning/generate-cards",
        json={"topic_id": "market", "topic_title": "市场与交易机制", "count": 10},
    )
    assert resp.status_code == 200
    cards = resp.json()["cards"]
    assert len(cards) == 10  # 分块并行 + 合并后达到目标
    assert len({c["title"] for c in cards}) == 10  # 跨块去重,标题唯一


def test_generate_cards_dedupes_within_batch_and_against_existing(monkeypatch):
    # 两条重复标题 + 一条与 existing 冲突,应被过滤
    batch = {"cards": [_good_card("A"), _good_card("A"), _good_card("旧的"), _good_card("B")]}
    monkeypatch.setattr(learning_routes, "_call_deepseek", lambda *a, **k: json.dumps(batch))
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    resp = TestClient(app).post(
        "/learning/generate-cards",
        json={"topic_id": "market", "topic_title": "t", "existing_titles": ["旧的"], "count": 10},
    )
    titles = [c["title"] for c in resp.json()["cards"]]
    assert titles == ["A", "B"]


def test_generate_cards_503_on_empty(monkeypatch):
    monkeypatch.setattr(learning_routes, "_call_deepseek", lambda *a, **k: json.dumps({"cards": []}))
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    resp = TestClient(app).post(
        "/learning/generate-cards",
        json={"topic_id": "market", "topic_title": "t", "count": 10},
    )
    assert resp.status_code == 503


def test_generate_cards_count_bounds():
    with pytest.raises(Exception):
        GenerateCardsRequest(topic_id="market", topic_title="t", count=99)


# ── 批量出题(generate-quiz-batch)──────────────────────────────────────────

def test_generate_quiz_batch_maps_by_id(monkeypatch):
    batch = {
        "items": [
            {"id": "risk-first", "type": "choice", "question": "q1",
             "options": ["对的做法", "错1", "错2", "错3"], "answer": 0, "explanation": "e1"},
            {"id": "risk-kelly", "type": "judge", "question": "q2",
             "options": ["对的做法", "错1", "错2", "错3"], "answer": 0, "explanation": "e2"},
        ]
    }
    monkeypatch.setattr(learning_routes, "_call_deepseek", lambda *a, **k: json.dumps(batch))
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    resp = TestClient(app).post(
        "/learning/generate-quiz-batch",
        json={"items": [
            {"id": "risk-first", "topic_title": "风险", "title": "止损", "core": "..."},
            {"id": "risk-kelly", "topic_title": "风险", "title": "凯利", "core": "..."},
        ]},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    by_id = {r["id"]: r for r in results}
    assert set(by_id) == {"risk-first", "risk-kelly"}
    assert by_id["risk-first"]["quiz"]["options"][by_id["risk-first"]["quiz"]["answer"]] == "对的做法"


def test_generate_quiz_batch_drops_unknown_and_dupe_ids(monkeypatch):
    batch = {
        "items": [
            {"id": "risk-first", "type": "choice", "question": "q", "options": ["对的做法", "b", "c", "d"], "answer": 0, "explanation": "e"},
            {"id": "risk-first", "type": "choice", "question": "dupe", "options": ["对的做法", "b", "c", "d"], "answer": 0, "explanation": "e"},
            {"id": "not-requested", "type": "choice", "question": "q", "options": ["对的做法", "b", "c", "d"], "answer": 0, "explanation": "e"},
        ]
    }
    monkeypatch.setattr(learning_routes, "_call_deepseek", lambda *a, **k: json.dumps(batch))
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    resp = TestClient(app).post(
        "/learning/generate-quiz-batch",
        json={"items": [{"id": "risk-first", "topic_title": "t", "title": "x", "core": "c"}]},
    )
    assert [r["id"] for r in resp.json()["results"]] == ["risk-first"]


# ── 跨设备状态同步(GET/PUT /learning/state)────────────────────────────────

def test_state_roundtrip(tmp_path, monkeypatch):
    # 把状态文件重定向到临时目录
    monkeypatch.setattr(learning_routes, "_state_path", lambda: tmp_path / "learning_state.json")
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    client = TestClient(app)

    # 初始为空
    assert client.get("/learning/state").json() == {"progress": None, "extra": None}

    # 写入后可读回
    payload = {"progress": {"version": 1, "read": {"a": 1}}, "extra": {"risk": []}}
    put = client.put("/learning/state", json=payload)
    assert put.status_code == 200
    got = client.get("/learning/state").json()
    assert got["progress"] == payload["progress"]
    assert got["extra"] == payload["extra"]


def test_state_corrupt_file_returns_empty(tmp_path, monkeypatch):
    path = tmp_path / "learning_state.json"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(learning_routes, "_state_path", lambda: path)
    app = FastAPI()
    register_learning_routes(app, require_auth=lambda: None)
    assert TestClient(app).get("/learning/state").json() == {"progress": None, "extra": None}
