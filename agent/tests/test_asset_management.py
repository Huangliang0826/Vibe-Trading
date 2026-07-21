from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.asset_management_routes import register_asset_management_routes
from src.asset_management import AssetManagementRequest, AssetManagementService, AssetManagementStore
from src.asset_management.service import _review_model


def _history(codes: list[str], start: str, end: str):
    del start, end
    index = pd.bdate_range("2021-01-01", periods=900)
    rng = np.random.default_rng(7)
    result = {}
    for offset, code in enumerate(codes):
        returns = rng.normal(0.00025 + offset * 0.00003, 0.010 + offset * 0.001, len(index))
        result[code] = pd.DataFrame({"close": 100 * np.cumprod(1 + returns)}, index=index)
    return result


def _request() -> AssetManagementRequest:
    return AssetManagementRequest.model_validate({
        "candidates": [
            {"symbol": "510300", "market": "cn", "name": "沪深300ETF", "asset_type": "fund"},
            {"symbol": "3032", "market": "hk", "name": "恒生科技ETF", "asset_type": "fund"},
            {"symbol": "1810", "market": "hk", "name": "小米", "asset_type": "stock"},
        ],
        "target_return": 0.065,
        "max_drawdown": 0.20,
    })


def _deepseek_decision() -> dict:
    return {
        "summary": "DeepSeek直接生成组合仓位。",
        "allocations": [
            {"symbol": "510300", "market": "cn", "weight": 0.20, "range_min": 0.15, "range_max": 0.25, "reason": "核心宽基。"},
            {"symbol": "3032", "market": "hk", "weight": 0.25, "range_min": 0.20, "range_max": 0.30, "reason": "科技成长。"},
            {"symbol": "1810", "market": "hk", "weight": 0.45, "range_min": 0.35, "range_max": 0.50, "reason": "个股增强。"},
            {"symbol": "CASH", "market": "cash", "weight": 0.10, "range_min": 0.05, "range_max": 0.15, "reason": "流动性。"},
        ],
        "warnings": ["关注科技资产集中度。"],
    }


def test_deepseek_weights_are_used_without_local_position_caps(tmp_path):
    store = AssetManagementStore(tmp_path / "latest.json")
    service = AssetManagementService(
        store,
        history_loader=_history,
        allocator=lambda payload: _deepseek_decision(),
    )

    plan = service.calculate(_request())

    assert abs(sum(item.weight for item in plan.allocations) - 1.0) < 1e-6
    assert next(item for item in plan.allocations if item.symbol == "1810").weight == 0.45
    assert [item.symbol for item in plan.allocations if item.asset_type != "cash"] == [
        item.symbol for item in _request().candidates
    ]
    assert plan.summary == "DeepSeek直接生成组合仓位。"
    assert "关注科技资产集中度。" in plan.warnings
    assert store.get_latest() == plan


def test_candidates_without_history_remain_visible_at_zero_weight(tmp_path):
    def partial_history(codes: list[str], start: str, end: str):
        history = _history(codes, start, end)
        history.pop(codes[-1])
        return history

    service = AssetManagementService(
        AssetManagementStore(tmp_path / "latest.json"),
        history_loader=partial_history,
        allocator=lambda payload: {
            **_deepseek_decision(),
            "allocations": [
                {**item, "weight": 0.0, "range_min": 0.0, "range_max": 0.0}
                if item["symbol"] == "1810" else item
                for item in _deepseek_decision()["allocations"]
            ],
        },
    )

    with pytest.raises(ValueError, match="合计"):
        service.calculate(_request())


def test_missing_history_uses_proxy_metrics_when_deepseek_allocates_it(tmp_path):
    def partial_history(codes: list[str], start: str, end: str):
        history = _history(codes, start, end)
        history.pop(codes[-1])
        return history

    service = AssetManagementService(
        AssetManagementStore(tmp_path / "latest.json"),
        history_loader=partial_history,
        allocator=lambda payload: _deepseek_decision(),
    )

    plan = service.calculate(_request())
    excluded = next(item for item in plan.allocations if item.symbol == "1810")

    assert excluded.weight == 0.45
    assert any("类型代理估计" in warning for warning in plan.warnings)


def test_routes_return_latest_successful_plan(tmp_path):
    service = AssetManagementService(
        AssetManagementStore(tmp_path / "latest.json"),
        history_loader=_history,
        allocator=lambda payload: _deepseek_decision(),
    )
    app = FastAPI()
    register_asset_management_routes(app, require_auth=lambda: None, service=service)
    client = TestClient(app)

    assert client.get("/asset-management/latest").json() is None
    response = client.post("/asset-management/calculate", json=_request().model_dump(mode="json"))
    assert response.status_code == 200
    latest = client.get("/asset-management/latest")
    assert latest.status_code == 200
    assert latest.json()["plan_id"] == response.json()["plan_id"]


def test_route_requires_deepseek_allocator(tmp_path):
    service = AssetManagementService(
        AssetManagementStore(tmp_path / "latest.json"),
        history_loader=_history,
        allocator=None,
    )
    app = FastAPI()
    register_asset_management_routes(app, require_auth=lambda: None, service=service)

    response = TestClient(app).post(
        "/asset-management/calculate",
        json=_request().model_dump(mode="json"),
    )

    assert response.status_code == 503
    assert "DeepSeek" in response.json()["detail"]


def test_duplicate_candidates_are_rejected():
    try:
        AssetManagementRequest.model_validate({
            "candidates": [
                {"symbol": "1810", "market": "hk"},
                {"symbol": "1810", "market": "hk"},
            ],
            "target_return": 0.07,
            "max_drawdown": 0.20,
        })
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate candidates should fail validation")


def test_asset_review_always_uses_official_deepseek():
    assert _review_model() == ("deepseek", "deepseek-v4-pro")


def test_official_deepseek_builder_never_falls_back_to_openai_key(monkeypatch, tmp_path):
    from src.providers import llm

    monkeypatch.setattr(llm, "_ensure_dotenv", lambda: None)
    monkeypatch.setattr(llm, "PROJECT_ENV_PATH", tmp_path / "missing.env")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        llm.build_official_deepseek_llm()


def test_official_deepseek_builder_uses_deepseek_credentials(monkeypatch, tmp_path):
    from src.providers import llm

    captured = {}

    class FakeDeepSeekClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, "_ensure_dotenv", lambda: None)
    monkeypatch.setattr(llm, "PROJECT_ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setattr(llm, "ChatOpenAIWithReasoning", FakeDeepSeekClient)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.example/v1")

    llm.build_official_deepseek_llm(model_name="deepseek-v4-pro")

    assert captured["api_key"] == "deepseek-test-key"
    assert captured["base_url"] == "https://api.deepseek.example/v1"
    assert captured["model"] == "deepseek-v4-pro"
    assert captured["vibe_provider"] == "deepseek"


def test_official_deepseek_builder_reads_web_settings_after_restart(monkeypatch, tmp_path):
    from src.providers import llm

    captured = {}

    class FakeDeepSeekClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    project_env = tmp_path / ".env"
    project_env.write_text(
        "DEEPSEEK_API_KEY=saved-from-web-settings\n"
        "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm, "_ensure_dotenv", lambda: None)
    monkeypatch.setattr(llm, "PROJECT_ENV_PATH", project_env)
    monkeypatch.setattr(llm, "ChatOpenAIWithReasoning", FakeDeepSeekClient)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "unrelated-key")

    llm.build_official_deepseek_llm()

    assert captured["api_key"] == "saved-from-web-settings"
    assert captured["base_url"] == "https://api.deepseek.com/v1"
