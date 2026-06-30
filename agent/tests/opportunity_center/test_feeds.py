from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.opportunity_center.storage import OpportunityStore


ATOM_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom</title>
  <entry>
    <id>tag:example.com,2026:story-1</id>
    <title>NVIDIA launches platform</title>
    <link href="https://example.com/story?utm_source=rss&amp;ref=feed#top" />
    <updated>2026-06-29T10:30:00Z</updated>
    <summary>Latest product launch.</summary>
  </entry>
</feed>
"""


def article_xml(index: int, now: datetime, *, title: str | None = None, url: str | None = None) -> str:
    published_at = (now - timedelta(hours=index)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    item_title = title or f"Story {index}"
    item_url = url or f"https://example.com/story-{index}?utm_medium=rss"
    return f"""\
    <item>
      <guid>story-{index}</guid>
      <title>{item_title}</title>
      <link>{item_url}</link>
      <pubDate>{published_at}</pubDate>
      <description>Summary {index}</description>
    </item>
    """


def rss_xml(items: list[str]) -> str:
    return f"""\
    <?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>Example RSS</title>
        {''.join(items)}
      </channel>
    </rss>
    """


def make_article(*, article_id: str, title: str, url: str, published_at: str, source: str = "OpenAI"):
    from src.opportunity_center.models import NewsArticle

    return NewsArticle(
        article_id=article_id,
        source=source,
        title=title,
        url=url,
        published_at=published_at,
        summary="summary",
    )


def test_canonicalize_url_removes_tracking_query_and_fragment():
    from src.opportunity_center.feeds import canonicalize_url

    assert canonicalize_url("https://example.com/path?utm_source=rss&id=7&ref=home#section") == (
        "https://example.com/path?id=7"
    )


def test_parse_atom_and_strip_tracking_query():
    from src.opportunity_center.feeds import NewsSource, parse_feed

    rows = parse_feed(
        ATOM_XML,
        NewsSource(name="Example", hint="ai", type="rss", url="https://example.com/feed.xml"),
        datetime(2026, 6, 29, tzinfo=timezone.utc),
    )

    assert len(rows) == 1
    assert rows[0].url == "https://example.com/story"
    assert rows[0].title == "NVIDIA launches platform"


def test_parse_atom_prefers_alternate_link_over_self_and_enclosure():
    from src.opportunity_center.feeds import NewsSource, parse_feed

    xml = """\
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>story-1</id>
        <title>Multi-link story</title>
        <link rel="self" href="https://example.com/feed/entry-1" />
        <link rel="enclosure" href="https://cdn.example.com/audio.mp3" />
        <link rel="alternate" href="https://example.com/story-1?utm_source=atom" />
        <updated>2026-06-29T10:30:00Z</updated>
      </entry>
    </feed>
    """

    rows = parse_feed(
        xml,
        NewsSource(name="Example", hint="ai", type="rss", url="https://example.com/feed.xml"),
        datetime(2026, 6, 29, tzinfo=timezone.utc),
    )

    assert [row.url for row in rows] == ["https://example.com/story-1"]


def test_parse_feed_filters_old_entries_and_limits_to_six():
    from src.opportunity_center.feeds import NewsSource, parse_feed

    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    old_pub = (now - timedelta(days=8)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    items = [article_xml(index, now) for index in range(7)]
    items.append(
        f"""\
        <item>
          <guid>old-story</guid>
          <title>Old Story</title>
          <link>https://example.com/old-story</link>
          <pubDate>{old_pub}</pubDate>
          <description>Old summary</description>
        </item>
        """
    )

    rows = parse_feed(
        rss_xml(items),
        NewsSource(name="Example", hint="ai", type="rss", url="https://example.com/feed.xml"),
        now,
    )

    assert len(rows) == 6
    assert [row.article_id for row in rows] == [f"example-story-{index}" for index in range(6)]


def test_feed_ingestor_dedupes_near_titles_against_recent_store_entries(tmp_path, monkeypatch):
    from src.opportunity_center.feeds import FeedIngestor

    store = OpportunityStore(tmp_path / "opportunities.db")
    store.upsert_articles(
        [
            make_article(
                article_id="existing-1",
                title="NVIDIA launches new AI platform",
                url="https://example.com/existing",
                published_at="2026-06-29T09:00:00Z",
                source="Seed Source",
            )
        ],
        source={
            "source_id": "seed-source",
            "name": "Seed Source",
            "sector": "ai",
            "url": "https://seed.example/rss.xml",
        },
    )

    source_path = tmp_path / "sources.json"
    source_path.write_text(
        json.dumps(
            {
                "fetch": {"per_source": 6, "timeout": 15, "recent_days": 7},
                "sources": [
                    {
                        "name": "Primary Source",
                        "hint": "ai",
                        "type": "rss",
                        "url": "https://source-a.example/rss.xml",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    feed_xml = rss_xml(
        [
            article_xml(
                0,
                datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc),
                title="Nvidia launches a new AI platform",
                url="https://example.com/near-duplicate?utm_source=rss",
            ),
            article_xml(
                1,
                datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc),
                title="Distinct robotics expansion",
                url="https://example.com/distinct-story?source=rss",
            ),
        ]
    )

    async def fake_fetch_source(self, client, source):
        assert source.url == "https://source-a.example/rss.xml"
        return feed_xml

    monkeypatch.setattr("src.opportunity_center.feeds.FeedIngestor._fetch_source", fake_fetch_source)

    ingestor = FeedIngestor(store, source_path)
    saved = ingestor.refresh(datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc))

    assert [article.title for article in saved] == ["Distinct robotics expansion"]
    assert [article.title for article in store.find_recent_articles(limit=10)] == [
        "Distinct robotics expansion",
        "NVIDIA launches new AI platform",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        "<rss><channel><item></rss>",
        "<html><body>Access denied</body></html>",
    ],
)
def test_parse_feed_rejects_malformed_or_non_feed_payloads(payload):
    from src.opportunity_center.feeds import FeedParseError, NewsSource, parse_feed

    source = NewsSource(name="Broken", hint="ai", type="rss", url="https://broken.example/rss.xml")

    with pytest.raises(FeedParseError, match="feed"):
        parse_feed(payload, source, datetime(2026, 6, 29, tzinfo=timezone.utc))


def test_parse_feed_accepts_valid_empty_feed():
    from src.opportunity_center.feeds import NewsSource, parse_feed

    source = NewsSource(name="Empty", hint="ai", type="rss", url="https://empty.example/rss.xml")

    assert parse_feed(rss_xml([]), source, datetime(2026, 6, 29, tzinfo=timezone.utc)) == []


def test_feed_ingestor_isolates_parse_failure_and_records_source_health(tmp_path, monkeypatch):
    from src.opportunity_center.feeds import FeedIngestor

    store = OpportunityStore(tmp_path / "opportunities.db")
    source_path = tmp_path / "sources.json"
    source_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "name": "Broken Source",
                        "hint": "ai",
                        "type": "rss",
                        "url": "https://broken.example/rss.xml",
                    },
                    {
                        "name": "Working Source",
                        "hint": "ai",
                        "type": "rss",
                        "url": "https://working.example/rss.xml",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)

    async def fake_fetch_source(self, client, source):
        if source.name == "Broken Source":
            return "<html><body>Rate limited</body></html>"
        return rss_xml([article_xml(0, now, title="Working story")])

    monkeypatch.setattr("src.opportunity_center.feeds.FeedIngestor._fetch_source", fake_fetch_source)

    saved = FeedIngestor(store, source_path).refresh(now)

    assert [article.title for article in saved] == ["Working story"]
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        health = {
            row["source_id"]: row
            for row in conn.execute(
                "SELECT source_id, consecutive_failures, last_success_at, last_error FROM news_sources"
            ).fetchall()
        }
    assert health["broken-source"]["consecutive_failures"] == 1
    assert "unsupported feed root" in health["broken-source"]["last_error"]
    assert health["working-source"]["consecutive_failures"] == 0
    assert health["working-source"]["last_success_at"] is not None
