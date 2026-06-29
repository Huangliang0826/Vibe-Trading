"""RSS/Atom ingestion for the opportunity center."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, ConfigDict

from src.opportunity_center.models import NewsArticle
from src.opportunity_center.storage import OpportunityStore, canonicalize_url as _canonicalize_url
from src.opportunity_center.storage import source_id_from_name, title_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_PER_SOURCE = 6
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_RECENT_DAYS = 7
MAX_CONCURRENCY = 12
TITLE_SIMILARITY_THRESHOLD = 0.92


class NewsSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    hint: str
    type: str
    url: str

    @property
    def source_id(self) -> str:
        return source_id_from_name(self.name)


@dataclass(frozen=True)
class _ArticleCandidate:
    article: NewsArticle
    source: NewsSource


def canonicalize_url(url: str) -> str:
    return _canonicalize_url(url)


def parse_feed(xml: str, source: NewsSource, now: datetime) -> list[NewsArticle]:
    root = _parse_xml(xml)
    if root is None:
        return []

    cutoff = _ensure_utc(now) - timedelta(days=DEFAULT_RECENT_DAYS)
    rows: list[NewsArticle] = []
    for item in _iter_entries(root):
        article = _article_from_entry(item, source)
        if article is None:
            continue
        published = _parse_datetime(article.published_at)
        if published is None or published < cutoff:
            continue
        rows.append(article.model_copy(update={"published_at": _to_iso_z(published), "url": canonicalize_url(article.url)}))

    rows.sort(key=lambda article: article.published_at, reverse=True)
    return _dedupe_articles(rows)[:DEFAULT_PER_SOURCE]


class FeedIngestor:
    def __init__(
        self,
        store: OpportunityStore,
        source_path: str | Path,
        max_concurrency: int = MAX_CONCURRENCY,
    ) -> None:
        self.store = store
        self.source_path = Path(source_path)
        payload = json.loads(self.source_path.read_text(encoding="utf-8"))
        fetch_cfg = payload.get("fetch", {})
        self.per_source = int(fetch_cfg.get("per_source", DEFAULT_PER_SOURCE))
        self.timeout_seconds = int(fetch_cfg.get("timeout", DEFAULT_TIMEOUT_SECONDS))
        self.recent_days = int(fetch_cfg.get("recent_days", DEFAULT_RECENT_DAYS))
        self.max_concurrency = max(1, min(int(max_concurrency), MAX_CONCURRENCY))
        self.sources = [NewsSource.model_validate(item) for item in payload.get("sources", [])]

    def refresh(self, now: datetime) -> list[NewsArticle]:
        return asyncio.run(self._refresh_async(now))

    async def _refresh_async(self, now: datetime) -> list[NewsArticle]:
        cutoff = _ensure_utc(now) - timedelta(days=self.recent_days)
        existing_articles = self.store.find_recent_articles(since=_to_iso_z(cutoff), limit=500)
        semaphore = asyncio.Semaphore(self.max_concurrency)
        candidates: list[_ArticleCandidate] = []

        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            tasks = [
                self._refresh_one_source(client, source, now, semaphore)
                for source in self.sources
            ]
            results = await asyncio.gather(*tasks)

        for source, parsed_articles, error in results:
            source_row = _source_row(source)
            if error is not None:
                self.store.upsert_articles([], source=source_row, error=error)
                continue
            self.store.upsert_articles([], source=source_row)
            for article in parsed_articles:
                candidates.append(_ArticleCandidate(article=article, source=source))

        unique_candidates = self._dedupe_against_recent(candidates, existing_articles)
        saved: list[NewsArticle] = []
        by_source: dict[str, list[NewsArticle]] = {}
        for candidate in unique_candidates:
            by_source.setdefault(candidate.source.source_id, []).append(candidate.article)

        source_map = {source.source_id: source for source in self.sources}
        for source_id, articles in by_source.items():
            source = source_map[source_id]
            persisted = self.store.upsert_articles(
                articles[: self.per_source],
                source=_source_row(source),
            )
            saved.extend(persisted)
        saved.sort(key=lambda article: article.published_at, reverse=True)
        return saved

    async def _refresh_one_source(
        self,
        client: httpx.AsyncClient,
        source: NewsSource,
        now: datetime,
        semaphore: asyncio.Semaphore,
    ) -> tuple[NewsSource, list[NewsArticle], str | None]:
        async with semaphore:
            try:
                xml = await self._fetch_source(client, source)
                parsed = parse_feed(xml, source, now)[: self.per_source]
                return source, parsed, None
            except Exception as exc:  # pragma: no cover - network path covered via monkeypatch
                logger.warning("feed refresh failed for %s: %s", source.name, exc)
                return source, [], str(exc)

    async def _fetch_source(self, client: httpx.AsyncClient, source: NewsSource) -> str:
        response = await client.get(source.url)
        response.raise_for_status()
        return response.text

    def _dedupe_against_recent(
        self,
        candidates: list[_ArticleCandidate],
        existing_articles: list[NewsArticle],
    ) -> list[_ArticleCandidate]:
        seen_urls = {canonicalize_url(article.url) for article in existing_articles}
        seen_titles: dict[str, list[str]] = {}
        for article in existing_articles:
            seen_titles.setdefault(article.published_at[:10], []).append(title_fingerprint(article.title))

        ordered = sorted(candidates, key=lambda row: row.article.published_at, reverse=True)
        kept: list[_ArticleCandidate] = []
        for candidate in ordered:
            article = candidate.article
            article_date = article.published_at[:10]
            normalized_title = title_fingerprint(article.title)
            if article.url in seen_urls:
                continue
            if _has_near_title_match(normalized_title, seen_titles.get(article_date, [])):
                continue
            kept.append(candidate)
            seen_urls.add(article.url)
            seen_titles.setdefault(article_date, []).append(normalized_title)
        return kept


def _parse_xml(xml: str) -> ElementTree.Element | None:
    try:
        return ElementTree.fromstring(xml.strip())
    except ElementTree.ParseError as exc:
        logger.warning("malformed feed xml: %s", exc)
        return None


def _iter_entries(root: ElementTree.Element) -> list[ElementTree.Element]:
    local_name = _local_name(root.tag)
    if local_name == "feed":
        return [child for child in root if _local_name(child.tag) == "entry"]
    if local_name == "rss":
        channel = next((child for child in root if _local_name(child.tag) == "channel"), None)
        if channel is None:
            return []
        return [child for child in channel if _local_name(child.tag) == "item"]
    if local_name == "channel":
        return [child for child in root if _local_name(child.tag) == "item"]
    return []


def _article_from_entry(entry: ElementTree.Element, source: NewsSource) -> NewsArticle | None:
    title = _clean_text(_child_text(entry, "title"))
    url = _entry_link(entry)
    published = _entry_published_at(entry)
    if not title or not url or not published:
        return None

    summary = _clean_text(
        _child_text(entry, "summary")
        or _child_text(entry, "description")
        or _child_text(entry, "encoded")
    )
    guid = _clean_text(_child_text(entry, "guid") or _child_text(entry, "id"))
    article_id = _build_article_id(source, guid=guid, url=url, title=title, published_at=published)
    return NewsArticle(
        article_id=article_id,
        source=source.name,
        title=title,
        url=url,
        published_at=published,
        summary=summary,
    )


def _entry_link(entry: ElementTree.Element) -> str:
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if child.text:
            return child.text.strip()
    return ""


def _entry_published_at(entry: ElementTree.Element) -> str:
    for tag in ("published", "updated", "pubDate"):
        raw = _child_text(entry, tag)
        if not raw:
            continue
        parsed = _parse_datetime(raw)
        if parsed is not None:
            return _to_iso_z(parsed)
    return ""


def _child_text(node: ElementTree.Element, tag_name: str) -> str:
    for child in node:
        if _local_name(child.tag) == tag_name:
            return "".join(child.itertext()).strip()
    return ""


def _clean_text(value: str) -> str:
    if not value:
        return ""
    stripped = re.sub(r"<[^>]+>", " ", value)
    normalized = re.sub(r"\s+", " ", unescape(stripped)).strip()
    return normalized


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(text)
        return _ensure_utc(dt)
    except ValueError:
        pass
    try:
        return _ensure_utc(parsedate_to_datetime(text))
    except (TypeError, ValueError):
        return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_iso_z(value: datetime) -> str:
    return _ensure_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dedupe_articles(articles: list[NewsArticle]) -> list[NewsArticle]:
    seen_urls: set[str] = set()
    seen_titles: dict[str, list[str]] = {}
    kept: list[NewsArticle] = []
    for article in articles:
        article_date = article.published_at[:10]
        normalized_title = title_fingerprint(article.title)
        if article.url in seen_urls:
            continue
        if _has_near_title_match(normalized_title, seen_titles.get(article_date, [])):
            continue
        kept.append(article)
        seen_urls.add(article.url)
        seen_titles.setdefault(article_date, []).append(normalized_title)
    return kept


def _has_near_title_match(title_value: str, seen_titles: list[str]) -> bool:
    from difflib import SequenceMatcher

    return any(
        SequenceMatcher(None, title_value, seen_title).ratio() >= TITLE_SIMILARITY_THRESHOLD
        for seen_title in seen_titles
    )


def _build_article_id(
    source: NewsSource,
    *,
    guid: str,
    url: str,
    title: str,
    published_at: str,
) -> str:
    candidate = _slugify_guid(guid) or _slugify_url(url) or _stable_hash(f"{title}|{published_at}")
    return f"{source.source_id}-{candidate}"


def _slugify_guid(guid: str) -> str:
    if not guid:
        return ""
    tail = guid.rsplit(":", 1)[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", tail.lower()).strip("-")
    return slug


def _slugify_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return slug


def _stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _source_row(source: NewsSource) -> dict[str, str]:
    return {
        "source_id": source.source_id,
        "name": source.name,
        "sector": source.hint,
        "url": source.url,
    }
