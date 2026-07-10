from __future__ import annotations

import pytest

from src.news_center.ai_digest import (
    ArkDigestClient,
    ArkDigestError,
    build_digest_prompt,
    extract_output_text,
    parse_digest_output,
)
from src.news_center.service import NewsCenterService
from src.opportunity_center.storage import OpportunityStore


# ── output extraction ────────────────────────────────────────────────────────

def test_extract_output_text_prefers_convenience_field() -> None:
    assert extract_output_text({"output_text": "hi", "output": []}) == "hi"


def test_extract_output_text_walks_message_items() -> None:
    data = {
        "output": [
            {"type": "web_search_call", "status": "completed"},
            {"type": "message", "content": [
                {"type": "output_text", "text": "part1"},
                {"type": "output_text", "text": "part2"},
            ]},
        ],
    }
    assert extract_output_text(data) == "part1\npart2"


def test_extract_output_text_tolerates_garbage() -> None:
    assert extract_output_text(None) == ""
    assert extract_output_text({"output": [{"type": "message", "content": None}]}) == ""


# ── parsing ──────────────────────────────────────────────────────────────────

def test_parse_digest_output_strips_fences_and_normalises_impact() -> None:
    text = '```json\n{"briefing": "总结", "major": [{"title": "T", "summary": "S", "impact": "BULLISH"}]}\n```'

    briefing, major = parse_digest_output(text)

    assert briefing == "总结"
    assert major == [{"title": "T", "summary": "S", "impact": "neutral"}]


def test_parse_digest_output_rejects_missing_briefing() -> None:
    with pytest.raises(ArkDigestError, match="briefing"):
        parse_digest_output('{"major": []}')


def test_parse_digest_output_rejects_non_json() -> None:
    with pytest.raises(ArkDigestError, match="JSON"):
        parse_digest_output("这不是 JSON")


# ── prompt ───────────────────────────────────────────────────────────────────

def test_build_digest_prompt_is_web_search_only_chinese() -> None:
    prompt = build_digest_prompt("2026-07-09")

    assert "2026-07-09" in prompt
    assert "联网搜索" in prompt
    assert "3~8" in prompt
    assert "简体中文" in prompt
    # Hard same-day constraint: stale search results must be rejected.
    assert "news_date" in prompt
    assert "前一天或更早的新闻一律不要" in prompt
    # Collected articles are never fed in — the prompt carries no article list.
    assert "新闻列表" not in prompt


def test_parse_digest_output_drops_items_dated_before_the_target_day() -> None:
    text = (
        '{"briefing": "总结", "major": ['
        '{"title": "今天的", "summary": "s", "news_date": "2026-07-09", "impact": "positive"},'
        '{"title": "昨天的", "summary": "s", "news_date": "2026-07-08", "impact": "positive"},'
        '{"title": "没日期的", "summary": "s", "impact": "neutral"}]}'
    )

    _briefing, major = parse_digest_output(text, "2026-07-09")

    titles = [m["title"] for m in major]
    assert "今天的" in titles
    assert "昨天的" not in titles
    # Undated items degrade gracefully rather than vanishing.
    assert "没日期的" in titles


def test_parse_digest_output_keeps_all_items_without_date_key() -> None:
    text = '{"briefing": "b", "major": [{"title": "T", "summary": "s", "news_date": "2020-01-01", "impact": "neutral"}]}'

    _briefing, major = parse_digest_output(text)

    assert len(major) == 1


# ── client guard ─────────────────────────────────────────────────────────────

def test_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    with pytest.raises(ArkDigestError, match="ARK_API_KEY"):
        ArkDigestClient(api_key="").generate("hi")


# ── service round-trip with real sqlite cache ────────────────────────────────

class FakeArticleStoreMixin:
    def list_news_center_articles(self, limit=500):
        return [
            {
                "article_id": "a1", "source": "Tech", "title": "腾讯发布新模型",
                "url": "https://example.com/a1", "published_at": "2026-07-09T09:00:00Z",
                "summary": "模型能力提升", "sector": "ai", "matches": [],
            },
        ]


class FakeAiClient:
    model = "doubao-test"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        return '{"briefing": "AI 简报正文", "major": [{"title": "大新闻", "summary": "摘要", "impact": "positive"}]}'


def _service(tmp_path) -> tuple[NewsCenterService, FakeAiClient]:
    store = OpportunityStore(db_path=tmp_path / "news.db")
    # Patch article listing onto the real store so the sqlite AI cache is exercised.
    store.list_news_center_articles = FakeArticleStoreMixin().list_news_center_articles  # type: ignore[method-assign]
    client = FakeAiClient()
    return NewsCenterService(store=store, feed_ingestor=object(), ai_client=client), client


def test_generate_ai_digest_caches_and_merges_into_digest(tmp_path) -> None:
    service, client = _service(tmp_path)

    digest = service.generate_ai_digest("2026-07-09", language="zh")

    assert digest.ai_summary == "AI 简报正文"
    assert digest.ai_major[0].title == "大新闻"
    assert digest.ai_major[0].impact == "positive"
    assert digest.ai_model == "doubao-test"
    assert client.calls == 1

    # Second call is served from cache — no new Ark call.
    again = service.generate_ai_digest("2026-07-09", language="zh")
    assert again.ai_summary == "AI 简报正文"
    assert client.calls == 1

    # Plain digest also carries the cached AI fields.
    plain = service.get_digest("2026-07-09", language="zh")
    assert plain.ai_summary == "AI 简报正文"

    # force=True regenerates.
    service.generate_ai_digest("2026-07-09", language="zh", force=True)
    assert client.calls == 2


def test_generate_ai_digest_is_a_noop_for_english(tmp_path) -> None:
    service, client = _service(tmp_path)

    digest = service.generate_ai_digest("2026-07-09", language="en")

    assert digest.ai_summary is None
    assert client.calls == 0


def test_digest_without_ai_cache_keeps_template_summary(tmp_path) -> None:
    service, _client = _service(tmp_path)

    digest = service.get_digest("2026-07-09", language="zh")

    assert digest.ai_summary is None
    assert digest.ai_major == []
    assert "腾讯发布新模型" in digest.summary


def test_digest_tolerates_stores_without_ai_cache_method() -> None:
    class BareStore(FakeArticleStoreMixin):
        pass

    service = NewsCenterService(store=BareStore(), feed_ingestor=object(), ai_client=FakeAiClient())

    digest = service.get_digest("2026-07-09", language="zh")

    assert digest.ai_summary is None
