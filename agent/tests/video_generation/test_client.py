from __future__ import annotations

import httpx

from src.video_generation.client import SeedanceClient


def test_create_task_builds_multimodal_seedance_payload(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request, json={"id": "cgt-test"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = SeedanceClient(api_key="test-key")
    result = client.create_task({
        "prompt": "生成一段产品短片",
        "image_urls": ["https://example.com/first.jpg"],
        "reference_video_url": "https://example.com/reference.mp4",
        "reference_audio_url": "https://example.com/music.mp3",
        "ratio": "9:16",
        "resolution": "1080p",
        "duration": 11,
        "generate_audio": True,
        "watermark": False,
    })

    assert result["id"] == "cgt-test"
    assert captured["json"]["model"] == "doubao-seedance-2-0-260128"
    assert captured["json"]["duration"] == 11
    assert [item["type"] for item in captured["json"]["content"]] == [
        "text", "image_url", "video_url", "audio_url",
    ]


def test_get_task_exposes_nested_video_url(monkeypatch):
    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, json={
            "id": "cgt-test",
            "status": "succeeded",
            "content": {"video_url": "https://example.com/result.mp4"},
        })

    monkeypatch.setattr(httpx, "get", fake_get)
    task = SeedanceClient(api_key="test-key").get_task("cgt-test")
    assert task["video_url"] == "https://example.com/result.mp4"
