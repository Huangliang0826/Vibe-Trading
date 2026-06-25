from __future__ import annotations

from pathlib import Path

from api_server import (
    _hstech_news_archive_dates,
    _load_hstech_news_archive,
    _store_hstech_news_archive,
)


def test_hstech_news_archive_stores_by_date_and_dedupes(tmp_path: Path) -> None:
    items = [
        {
            "title": "恒生科技指数上涨",
            "summary": "科技股反弹",
            "time": "2026-06-25 10:00:00",
            "source": "测试源",
            "url": "https://example.com/a",
        },
        {
            "title": "恒生科技指数上涨",
            "summary": "重复新闻",
            "time": "2026-06-25 10:00:00",
            "source": "测试源",
            "url": "https://example.com/a",
        },
        {
            "title": "港股科技回调",
            "summary": "隔日新闻",
            "time": "2026-06-24 15:00:00",
            "source": "测试源",
            "url": "https://example.com/b",
        },
    ]

    _store_hstech_news_archive(items, archive_dir=tmp_path)
    _store_hstech_news_archive(items, archive_dir=tmp_path)

    assert _hstech_news_archive_dates(archive_dir=tmp_path) == ["2026-06-25", "2026-06-24"]

    latest = _load_hstech_news_archive("2026-06-25", archive_dir=tmp_path)
    assert len(latest) == 1
    assert latest[0]["title"] == "恒生科技指数上涨"
