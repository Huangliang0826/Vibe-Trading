"""Cached LLM-based article impact analysis."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.opportunity_center.matching import NewsMatch
from src.opportunity_center.models import NewsImpact, StockContext
from src.opportunity_center.storage import OpportunityStore
from src.providers.chat import ChatLLM

logger = logging.getLogger(__name__)

NEWS_PROMPT_VERSION = "news-impact-v1"
MATCH_LIMITS = {"direct": 10, "industry": 5, "macro": 3}
BATCH_SIZE = 12


class NewsAnalyzer:
    def __init__(self, store: OpportunityStore, llm_factory: Any = ChatLLM) -> None:
        self.store = store
        self._llm = llm_factory()

    def analyze(
        self,
        context: StockContext,
        matches: list[NewsMatch],
        analysis_date: str,
    ) -> list[NewsImpact]:
        selected = _select_matches(matches)
        cached_or_new: dict[str, NewsImpact] = {}
        uncached: list[NewsMatch] = []

        for match in selected:
            cached = self.store.get_news_analysis(
                match.article.article_id,
                context.market,
                context.code,
                analysis_date,
                NEWS_PROMPT_VERSION,
            )
            if cached is not None:
                cached_or_new[match.article.article_id] = cached
            else:
                uncached.append(match)

        for batch in _batched(uncached, BATCH_SIZE):
            parsed = self._analyze_batch(context, batch)
            if parsed is None:
                continue
            requested = {match.article.article_id: match for match in batch}
            for item in parsed:
                article_id = str(item.get("article_id") or "").strip()
                match = requested.get(article_id)
                if match is None:
                    continue
                try:
                    impact = NewsImpact.model_validate(
                        {
                            "article_id": article_id,
                            "market": context.market,
                            "code": context.code,
                            "direction": item.get("direction"),
                            "strength": item.get("strength"),
                            "confidence": item.get("confidence"),
                            "horizon": item.get("horizon"),
                            "summary": item.get("summary") or "",
                            "rationale": item.get("rationale") or "",
                            "match_level": match.match_level,
                        }
                    )
                except Exception as exc:
                    logger.warning("invalid news impact payload for %s: %s", article_id, exc)
                    continue
                cached_or_new[article_id] = self.store.save_news_analysis(
                    impact,
                    analysis_date,
                    NEWS_PROMPT_VERSION,
                )

        return [
            cached_or_new[match.article.article_id]
            for match in selected
            if match.article.article_id in cached_or_new
        ]

    def _analyze_batch(self, context: StockContext, batch: list[NewsMatch]) -> list[dict[str, Any]] | None:
        payload = {
            "prompt_version": NEWS_PROMPT_VERSION,
            "market": context.market,
            "code": context.code,
            "company_name": context.company_name,
            "articles": [
                {
                    "article_id": match.article.article_id,
                    "title": match.article.title,
                    "summary": match.article.summary,
                    "published_at": match.article.published_at,
                    "match_level": match.match_level,
                }
                for match in batch
            ],
            "response_schema": "Return {'items': [{article_id, direction, strength, confidence, horizon, summary, rationale}, ...]}",
        }
        response = self._llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Analyze each article's likely stock impact. Return one JSON object only with an "
                        "\"items\" array. Do not include markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            timeout=60,
        )
        raw_text = getattr(response, "content", response)
        if not isinstance(raw_text, str):
            logger.warning("malformed news analysis response: missing text content")
            return None

        cleaned = _strip_markdown_fences(raw_text)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("malformed news analysis JSON: %s", exc)
            return None
        if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
            logger.warning("malformed news analysis payload: missing items array")
            return None
        return [item for item in parsed["items"] if isinstance(item, dict)]


def _select_matches(matches: list[NewsMatch]) -> list[NewsMatch]:
    selected: list[NewsMatch] = []
    for level in ("direct", "industry", "macro"):
        bucket = [match for match in matches if match.match_level == level]
        bucket.sort(key=lambda row: row.article.published_at, reverse=True)
        selected.extend(bucket[: MATCH_LIMITS[level]])
    return selected


def _batched(items: list[NewsMatch], size: int) -> list[list[NewsMatch]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def _strip_markdown_fences(value: str) -> str:
    text = value.strip()
    if not text.startswith("```"):
        return text
    text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()
