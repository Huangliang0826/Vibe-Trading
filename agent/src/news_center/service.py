from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import logging
import re
import threading
import time
from typing import Any

from src.news_center.ai_digest import (
    ArkDigestClient,
    ArkDigestError,
    build_fallback_digest,
    build_local_digest_prompt,
    build_web_enrichment_prompt,
    parse_digest_output,
)
from src.news_center.models import (
    NewsAiMajorItem,
    NewsCenterArticle,
    NewsCenterDigest,
    NewsCenterList,
    NewsCenterRefreshResult,
)
from src.opportunity_center.feeds import FeedIngestor
from src.opportunity_center.storage import OpportunityStore

logger = logging.getLogger(__name__)


class NewsCenterService:
    # Shared across service instances so startup pre-generation and HTTP
    # requests cannot launch duplicate model calls for the same day.
    _shared_digest_locks: dict[tuple[str, str], Any] = {}
    _shared_digest_locks_guard = threading.Lock()

    def __init__(
        self,
        *,
        store: Any | None = None,
        feed_ingestor: Any | None = None,
        ai_client: Any | None = None,
    ) -> None:
        self.store = store or OpportunityStore()
        self.feed_ingestor = feed_ingestor or FeedIngestor(
            self.store, Path(__file__).parents[1] / "opportunity_center" / "sources.json"
        )
        self.ai_client = ai_client or ArkDigestClient()

    def list_articles(
        self,
        *,
        date_key: str | None = None,
        sector: str | None = None,
        direction: str | None = None,
        query: str | None = None,
        symbol: str | None = None,
        watchlist_only: bool = False,
        language: str = "zh",
        limit: int = 200,
    ) -> NewsCenterList:
        rows = self._current_rows()
        items = [self._article(row) for row in rows]
        if date_key:
            items = [item for item in items if item.published_at[:10] == date_key]
        items = [item for item in items if item.language == language]
        if sector:
            items = [item for item in items if item.sector == sector]
        if direction:
            items = [item for item in items if any(m.direction == direction for m in item.matches)]
        if symbol:
            normalized = symbol.strip().upper()
            items = [item for item in items if any(m.code.upper() == normalized for m in item.matches)]
        if watchlist_only:
            items = [item for item in items if item.matches]
        if query:
            needle = query.strip().casefold()
            items = [
                item for item in items
                if needle in f"{item.title} {item.summary} {item.source}".casefold()
            ]
        items.sort(key=lambda item: (item.importance, item.published_at), reverse=True)
        sectors = sorted({item.sector for item in items if item.sector})
        return NewsCenterList(items=items[: max(1, min(limit, 500))], total=len(items), sectors=sectors)

    def get_dates(self) -> list[str]:
        rows = self._current_rows()
        return sorted({str(row["published_at"])[:10] for row in rows}, reverse=True)

    def get_digest(self, date_key: str, language: str = "zh") -> NewsCenterDigest:
        result = self.list_articles(date_key=date_key, language=language, limit=500)
        items = result.items
        major = [item for item in items if item.major][:5] or items[:5]
        positive = sum(any(m.direction == "positive" for m in item.matches) for item in items)
        negative = sum(any(m.direction == "negative" for m in item.matches) for item in items)
        watchlist = sum(bool(item.matches) for item in items)
        if not items:
            summary = "当日暂无已收录新闻。"
        else:
            headlines = "；".join(item.title for item in major[:3])
            summary = (
                f"{date_key} 共收录 {len(items)} 条新闻，其中 {watchlist} 条关联自选股。"
                f"重点关注：{headlines}。"
            )
        digest = NewsCenterDigest(
            date=date_key,
            article_count=len(items),
            watchlist_count=watchlist,
            positive_count=positive,
            negative_count=negative,
            summary=summary,
            major_items=major,
        )
        return self._merge_ai_digest(digest, date_key, language)

    def _merge_ai_digest(
        self, digest: NewsCenterDigest, date_key: str, language: str,
    ) -> NewsCenterDigest:
        """Attach the cached AI briefing when one exists (never generates)."""
        getter = getattr(self.store, "get_news_ai_digest", None)
        cached = getter(date_key, language) if callable(getter) else None
        if not cached:
            return digest
        digest.ai_summary = str(cached.get("briefing") or "") or None
        digest.ai_major = [NewsAiMajorItem(**row) for row in cached.get("major") or []]
        digest.ai_generated_at = cached.get("generated_at")
        digest.ai_model = cached.get("model")
        digest.ai_source = str(cached.get("source") or "web")
        return digest

    def _digest_lock(self, date_key: str, language: str) -> Any:
        key = (date_key, language)
        with self._shared_digest_locks_guard:
            return self._shared_digest_locks.setdefault(key, threading.RLock())

    def _prompt_articles(self, date_key: str, language: str) -> list[dict[str, str]]:
        result = self.list_articles(date_key=date_key, language=language, limit=100)
        articles: list[dict[str, str]] = []
        for item in result.items:
            directions = {match.direction for match in item.matches if match.direction}
            impact = (
                "positive" if "positive" in directions
                else "negative" if "negative" in directions
                else "neutral"
            )
            articles.append({
                "title": item.title,
                "summary": item.summary,
                "source": item.source,
                "impact": impact,
            })
        return articles

    def generate_ai_digest(
        self, date_key: str, language: str = "zh", force: bool = False,
    ) -> NewsCenterDigest:
        """Generate a fast digest from articles already collected for the day.

        The slower web verification is handled separately by
        :meth:`enrich_ai_digest` so this method can return quickly.
        """
        if language != "zh":
            return self.get_digest(date_key, language=language)
        with self._digest_lock(date_key, language):
            if not force:
                cached = self.store.get_news_ai_digest(date_key, language)
                if cached:
                    return self.get_digest(date_key, language=language)
            articles = self._prompt_articles(date_key, language)
            prompt = build_local_digest_prompt(date_key, articles)
            started = time.monotonic()
            source = "local"
            model = self.ai_client.model
            try:
                briefing, major = parse_digest_output(
                    self.ai_client.generate(prompt, web_search=False), date_key,
                )
                logger.info(
                    "news AI local digest completed for %s in %.2fs (%d articles)",
                    date_key, time.monotonic() - started, len(articles),
                )
            except ArkDigestError as exc:
                logger.warning(
                    "news AI local digest unavailable for %s after %.2fs; using local fallback: %s",
                    date_key, time.monotonic() - started, exc,
                )
                briefing, major = build_fallback_digest(date_key, articles)
                source = "fallback"
                model = "local-fallback"
            self.store.save_news_ai_digest(
                date_key, language,
                {"briefing": briefing, "major": major, "source": source},
                model,
            )
        return self.get_digest(date_key, language=language)

    def enrich_ai_digest(self, date_key: str, language: str = "zh") -> NewsCenterDigest:
        """Verify and enrich a cached local digest with focused web search."""
        if language != "zh":
            return self.get_digest(date_key, language=language)
        with self._digest_lock(date_key, language):
            cached = self.store.get_news_ai_digest(date_key, language)
            if cached and cached.get("source") == "web":
                return self.get_digest(date_key, language=language)
            if not cached:
                self.generate_ai_digest(date_key, language=language)
                cached = self.store.get_news_ai_digest(date_key, language) or {}
            articles = self._prompt_articles(date_key, language)
            prompt = build_web_enrichment_prompt(
                date_key, str(cached.get("briefing") or ""), articles,
            )
            started = time.monotonic()
            briefing, major = parse_digest_output(
                self.ai_client.generate(prompt, web_search=True), date_key,
            )
            logger.info(
                "news AI web enrichment completed for %s in %.2fs (%d candidates)",
                date_key, time.monotonic() - started, min(len(articles), 10),
            )
            self.store.save_news_ai_digest(
                date_key, language,
                {"briefing": briefing, "major": major, "source": "web"},
                self.ai_client.model,
            )
        return self.get_digest(date_key, language=language)

    def refresh(self) -> NewsCenterRefreshResult:
        saved = self.feed_ingestor.refresh(datetime.now(timezone.utc))
        rows = self._current_rows()
        latest = max((str(row["published_at"])[:10] for row in rows), default=None)
        return NewsCenterRefreshResult(fetched=len(saved), total=len(rows), latest_date=latest)

    def _current_rows(self) -> list[dict[str, Any]]:
        today = date.today().isoformat()
        return [
            row for row in self.store.list_news_center_articles(limit=500)
            if str(row["published_at"])[:10] <= today
        ]

    @staticmethod
    def _article(row: dict[str, Any]) -> NewsCenterArticle:
        matches = list(row.get("matches", []))
        direct = any(match.get("match_level") == "direct" for match in matches)
        strength = max((float(match.get("strength") or 0) for match in matches), default=0)
        macro = row.get("sector") == "macro"
        importance = strength + (30 if direct else 15 if matches else 0) + (10 if macro else 0)
        language = _detect_language(str(row.get("title", "")), str(row.get("summary", "")))
        return NewsCenterArticle(
            **row, importance=importance, major=direct or strength >= 70 or macro,
            language=language,
        )


_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _detect_language(title: str, summary: str) -> str:
    """Classify mixed Chinese headlines as Chinese; otherwise inspect the summary."""
    if _CJK_RE.search(title):
        return "zh"
    cjk_count = len(_CJK_RE.findall(summary))
    return "zh" if cjk_count >= 2 else "en"
