from __future__ import annotations

from src.news_center.service import NewsCenterService


class FakeStore:
    def list_news_center_articles(self, limit=500):
        return [
            {
                "article_id": "a1", "source": "Macro", "title": "央行维持利率",
                "url": "https://example.com/a1", "published_at": "2026-07-01T08:00:00Z",
                "summary": "政策保持稳定", "sector": "macro",
                "matches": [],
            },
            {
                "article_id": "a2", "source": "Tech", "title": "腾讯发布新模型",
                "url": "https://example.com/a2", "published_at": "2026-07-01T09:00:00Z",
                "summary": "模型能力提升", "sector": "ai",
                "matches": [{
                    "market": "hk", "code": "0700", "match_level": "direct",
                    "confidence": 90, "direction": "positive", "strength": 85,
                }],
            },
            {
                "article_id": "old", "source": "Tech", "title": "昨日新闻",
                "url": "https://example.com/old", "published_at": "2026-06-30T09:00:00Z",
                "summary": "旧闻", "sector": "ai", "matches": [],
            },
            {
                "article_id": "en1", "source": "Reuters", "title": "Nvidia unveils new AI chips",
                "url": "https://example.com/en1", "published_at": "2026-07-01T10:00:00Z",
                "summary": "The company announced its next generation platform.", "sector": "ai",
                "matches": [],
            },
            {
                "article_id": "future", "source": "Bad clock", "title": "未来新闻",
                "url": "https://example.com/future", "published_at": "2099-01-01T09:00:00Z",
                "summary": "错误日期", "sector": "macro", "matches": [],
            },
        ]


def test_filters_articles_by_date_sector_direction_and_watchlist():
    service = NewsCenterService(store=FakeStore(), feed_ingestor=object())

    result = service.list_articles(
        date_key="2026-07-01", sector="ai", direction="positive", watchlist_only=True,
    )

    assert [item.article_id for item in result.items] == ["a2"]


def test_digest_only_uses_selected_date_and_prioritizes_direct_impact():
    service = NewsCenterService(store=FakeStore(), feed_ingestor=object())

    digest = service.get_digest("2026-07-01")

    assert digest.article_count == 2
    assert digest.major_items[0].article_id == "a2"
    assert "腾讯发布新模型" in digest.summary
    assert "昨日新闻" not in digest.summary


def test_future_dated_feed_items_are_not_exposed():
    service = NewsCenterService(store=FakeStore(), feed_ingestor=object())

    assert "2099-01-01" not in service.get_dates()
    assert all(item.article_id != "future" for item in service.list_articles().items)


def test_filters_articles_and_digest_by_detected_language():
    service = NewsCenterService(store=FakeStore(), feed_ingestor=object())

    chinese = service.list_articles(date_key="2026-07-01", language="zh")
    english = service.list_articles(date_key="2026-07-01", language="en")

    assert {item.article_id for item in chinese.items} == {"a1", "a2"}
    assert [item.article_id for item in english.items] == ["en1"]
    assert service.get_digest("2026-07-01", language="en").article_count == 1
    assert "Nvidia unveils new AI chips" in service.get_digest("2026-07-01", language="en").summary
