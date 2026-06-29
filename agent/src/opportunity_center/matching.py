"""Article matching for opportunity-center stocks."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.opportunity_center.models import MatchLevel, NewsArticle, StockContext

LEVEL_ORDER: dict[str, int] = {"direct": 0, "industry": 1, "macro": 2}
MACRO_KEYWORDS = {
    "fed",
    "federalreserve",
    "interestrate",
    "rates",
    "inflation",
    "cpi",
    "pmi",
    "gdp",
    "yield",
    "treasury",
    "tariff",
    "centralbank",
    "jobs",
    "macro",
}
INDUSTRY_SYNONYMS = {
    "semiconductors": {"semiconductor", "chip", "chips", "foundry", "gpu"},
    "technology": {"tech", "software", "hardware"},
}


class NewsMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article: NewsArticle
    match_level: MatchLevel
    confidence: float = Field(ge=0, le=1)


def build_stock_context(
    market: str,
    code: str,
    quote_name: str,
    profile: dict[str, Any] | None,
) -> StockContext:
    profile = profile or {}
    company_name = _first_non_empty(
        quote_name,
        str(profile.get("longName") or ""),
        str(profile.get("shortName") or ""),
        code,
    )
    aliases = _dedupe_strings(
        [
            code,
            quote_name,
            str(profile.get("shortName") or ""),
            str(profile.get("longName") or ""),
            str(profile.get("displayName") or ""),
        ]
    )
    brands = _listify(profile.get("brands")) or _listify(profile.get("brand"))
    products = _listify(profile.get("products")) or _listify(profile.get("product"))
    return StockContext(
        market=market,
        code=code,
        company_name=company_name,
        aliases=aliases,
        brands=_dedupe_strings(brands),
        products=_dedupe_strings(products),
        sector=str(profile.get("sector") or ""),
        industry=str(profile.get("industry") or ""),
    )


def match_articles(context: StockContext, articles: list[NewsArticle]) -> list[NewsMatch]:
    matches: list[NewsMatch] = []
    for article in articles:
        matched = _match_one(context, article)
        if matched is not None:
            matches.append(matched)
    matches.sort(
        key=lambda row: (
            LEVEL_ORDER[row.match_level],
            -row.confidence,
            -_published_timestamp(row.article.published_at),
        )
    )
    return matches


def _match_one(context: StockContext, article: NewsArticle) -> NewsMatch | None:
    text = _normalize_text(f"{article.title} {article.summary}")
    direct_terms = _direct_terms(context)
    matched_direct = [term for term in direct_terms if _contains_term(text, term)]
    if matched_direct:
        confidence = 0.88
        if any(term in _normalize_text(" ".join(context.products + context.brands)) for term in matched_direct):
            confidence = 0.95
        return NewsMatch(article=article, match_level="direct", confidence=min(0.99, confidence + 0.02 * max(0, len(matched_direct) - 1)))

    industry_terms = _industry_terms(context)
    matched_industry = [term for term in industry_terms if _contains_term(text, term)]
    if matched_industry:
        confidence = min(0.79, 0.62 + 0.04 * max(0, len(matched_industry) - 1))
        return NewsMatch(article=article, match_level="industry", confidence=confidence)

    matched_macro = [term for term in MACRO_KEYWORDS if term in text]
    if matched_macro:
        confidence = min(0.49, 0.34 + 0.03 * max(0, len(matched_macro) - 1))
        return NewsMatch(article=article, match_level="macro", confidence=confidence)
    return None


def _direct_terms(context: StockContext) -> list[str]:
    terms = [
        context.code,
        context.company_name,
        *context.aliases,
        *context.brands,
        *context.products,
    ]
    return _expand_terms(terms)


def _industry_terms(context: StockContext) -> list[str]:
    terms = _expand_terms([context.sector, context.industry])
    for raw in (context.sector, context.industry):
        normalized = _normalize_text(raw)
        terms.extend(sorted(INDUSTRY_SYNONYMS.get(normalized, set())))
    return _dedupe_strings(terms)


def _expand_terms(values: list[str]) -> list[str]:
    expanded: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if len(normalized) < 2:
            continue
        expanded.append(normalized)
        if normalized.endswith("s") and len(normalized) > 4:
            expanded.append(normalized[:-1])
    return _dedupe_strings(expanded)


def _contains_term(text: str, term: str) -> bool:
    return bool(term) and term in text


def _listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,/;|]+", value) if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = value.strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(text)
    return ordered


def _normalize_text(value: str) -> str:
    collapsed = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", value).strip().lower()
    return collapsed.replace(" ", "")


def _first_non_empty(*values: str) -> str:
    for value in values:
        text = value.strip()
        if text:
            return text
    return ""


def _published_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return 0.0
