from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import requests

from src.historical_events.models import EvidenceItem

ALPACA_ENV_PATH = Path(__file__).parents[2] / ".env"


class NewsProvider(Protocol):
    def search(
        self, symbol: str, company_name: str, start: date, end: date,
    ) -> list[EvidenceItem]: ...


class EastMoneyNewsProvider:
    """HK finance news using the same EastMoney feed as the HSTECH news panel."""

    def __init__(self, fetcher: Callable[[str], pd.DataFrame] | None = None) -> None:
        self._fetcher = fetcher
        self._frames: dict[str, pd.DataFrame] = {}

    def search(
        self, symbol: str, company_name: str, start: date, end: date,
    ) -> list[EvidenceItem]:
        fetcher = self._fetcher or _eastmoney_fetcher
        terms = _unique([company_name if company_name.strip() != symbol.strip() else symbol])
        collected: dict[str, EvidenceItem] = {}
        for term in terms:
            try:
                if term not in self._frames:
                    self._frames[term] = fetcher(term)
                frame = self._frames[term]
            except Exception:
                continue
            if frame is None or frame.empty:
                continue
            for _, row in frame.iterrows():
                title = _clean_html(str(row.get("新闻标题") or ""))
                snippet = _clean_html(str(row.get("新闻内容") or ""))
                published_at = _parse_date(row.get("发布时间"))
                url = str(row.get("新闻链接") or "").strip()
                if not title or published_at is None or not start <= published_at <= end:
                    continue
                if not _mentions_target(title, symbol, company_name):
                    continue
                item = EvidenceItem(
                    title=title, url=url, snippet=snippet[:600],
                    source=str(row.get("文章来源") or "东方财富").strip() or "东方财富",
                    published_at=published_at, evidence_type=_evidence_type(f"{title} {snippet}"),
                    related_symbols=[symbol.upper()],
                )
                collected[url or f"{published_at}:{title}"] = item
        return sorted(collected.values(), key=lambda item: item.published_at or date.min, reverse=True)


class AlpacaNewsProvider:
    """US historical news from Alpaca/Benzinga, filtered by exact symbol and date."""

    endpoint = "https://data.alpaca.markets/v1beta1/news"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        secret_key: str | None = None,
        session: Any | None = None,
    ) -> None:
        saved_key, saved_secret = _alpaca_credentials()
        self.api_key = api_key or saved_key
        self.secret_key = secret_key or saved_secret
        self.session = session or requests.Session()

    def search(
        self, symbol: str, company_name: str, start: date, end: date,
    ) -> list[EvidenceItem]:
        if not self.api_key or not self.secret_key:
            return []
        normalized = symbol.strip().upper()
        params: dict[str, Any] = {
            "symbols": normalized,
            "start": datetime.combine(start, time.min, timezone.utc).isoformat(),
            "end": datetime.combine(end + timedelta(days=1), time.min, timezone.utc).isoformat(),
            "limit": 50,
            "sort": "desc",
            "include_content": "true",
        }
        headers = {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key}
        evidence: list[EvidenceItem] = []
        for _ in range(3):
            try:
                response = self.session.get(self.endpoint, headers=headers, params=params, timeout=20)
                response.raise_for_status()
                payload = response.json()
            except Exception:
                return evidence
            for row in payload.get("news", []):
                symbols = {str(value).upper() for value in row.get("symbols", [])}
                published_at = _parse_date(row.get("created_at") or row.get("updated_at"))
                if normalized not in symbols or published_at is None or not start <= published_at <= end:
                    continue
                title = str(row.get("headline") or "").strip()
                url = str(row.get("url") or "").strip()
                if not title or not url:
                    continue
                snippet = _clean_html(str(row.get("summary") or row.get("content") or ""))
                evidence.append(EvidenceItem(
                    title=title, url=url, snippet=snippet[:600],
                    source=str(row.get("source") or "Benzinga").strip(),
                    published_at=published_at, evidence_type=_evidence_type(f"{title} {snippet}"),
                    related_symbols=sorted(symbols),
                ))
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        return evidence


class EvidenceSearcher:
    def __init__(
        self,
        *,
        hk_provider: NewsProvider | None = None,
        us_provider: NewsProvider | None = None,
    ) -> None:
        self.hk_provider = hk_provider or EastMoneyNewsProvider()
        self.us_provider = us_provider or AlpacaNewsProvider()

    def search(
        self, market: str, symbol: str, company_name: str, start_date: date, end_date: date,
    ) -> list[EvidenceItem]:
        search_start = start_date - timedelta(days=3)
        search_end = end_date + timedelta(days=2)
        provider = self.hk_provider if market == "hk" else self.us_provider if market == "us" else None
        if provider is None:
            return []
        items = provider.search(symbol, company_name, search_start, search_end)
        valid = [item for item in items if item.published_at and search_start <= item.published_at <= search_end]
        valid.sort(
            key=lambda item: _relevance_score(item, symbol, company_name, start_date, end_date),
            reverse=True,
        )
        return valid[:12]


def _eastmoney_fetcher(term: str) -> pd.DataFrame:
    endpoint = "https://search-api-web.eastmoney.com/search/jsonp"
    callback = "jQuery35101792940631092459_1764599530165"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://so.eastmoney.com/news/s",
    }
    rows: list[dict[str, Any]] = []
    for page_index in range(1, 15):
        request_payload = {
            "uid": "", "keyword": term, "type": ["cmsArticleWebOld"],
            "client": "web", "clientType": "web", "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {
                "searchScope": "default", "sort": "default", "pageIndex": page_index,
                "pageSize": 100, "preTag": "", "postTag": "",
            }},
        }
        response = requests.get(
            endpoint,
            params={"cb": callback, "param": json.dumps(request_payload, ensure_ascii=False), "_": "1"},
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        payload = json.loads(response.text[len(callback) + 1:-1])
        page = payload.get("result", {}).get("cmsArticleWebOld", [])
        if not page:
            break
        rows.extend(page)
    return pd.DataFrame([
        {
            "新闻标题": row.get("title", ""),
            "新闻内容": row.get("content", ""),
            "发布时间": row.get("date", ""),
            "文章来源": row.get("mediaName", ""),
            "新闻链接": f"https://finance.eastmoney.com/a/{row.get('code', '')}.html",
        }
        for row in rows
    ])


def _alpaca_credentials() -> tuple[str, str]:
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID") or ""
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY") or ""
    if key and secret:
        return key.strip(), secret.strip()
    try:
        from dotenv import dotenv_values

        values = dotenv_values(ALPACA_ENV_PATH)
        file_key = str(values.get("ALPACA_API_KEY") or values.get("APCA_API_KEY_ID") or "").strip()
        file_secret = str(values.get("ALPACA_SECRET_KEY") or values.get("APCA_API_SECRET_KEY") or "").strip()
        if file_key and file_secret:
            return file_key, file_secret
    except Exception:
        pass
    try:
        from src.trading.connectors.alpaca.sdk import load_config

        config = load_config()
        return str(config.api_key or "").strip(), str(config.secret_key or "").strip()
    except Exception:
        return "", ""


def _mentions_target(text: str, symbol: str, company_name: str) -> bool:
    normalized = text.casefold()
    company = company_name.strip().casefold()
    if company and company != symbol.casefold() and company in normalized:
        return True
    return bool(re.search(rf"(?<!\w){re.escape(symbol.casefold())}(?!\w)", normalized))


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
        if not match:
            return None
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None


def _clean_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _evidence_type(text: str) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in ("results", "earnings", "业绩", "财报")):
        return "财报"
    if any(word in lowered for word in ("announcement", "filing", "公告")):
        return "公司公告"
    if any(word in lowered for word in ("regulator", "regulation", "监管", "政策")):
        return "监管政策"
    if any(word in lowered for word in ("sector", "industry", "行业")):
        return "行业事件"
    return "财经新闻"


def _relevance_score(
    item: EvidenceItem, symbol: str, company_name: str, event_start: date, event_end: date,
) -> float:
    title = item.title.casefold()
    score = 0.0
    company = company_name.strip().casefold()
    if company in title or symbol.casefold() in title:
        score += 4
    company_token = company.split()[0] if company else ""
    if company_token and len(company_token) >= 3 and title.startswith(company_token):
        score += 6
    direct_terms = (
        "earnings", "results", "revenue", "profit", "guidance", "forecast",
        "announces", "acquisition", "merger", "approval", "investigation", "lawsuit",
        "财报", "业绩", "营收", "利润", "指引", "公告", "收购", "合并", "批准", "调查", "诉讼",
    )
    score += 8 * sum(term in title for term in direct_terms)
    if any(phrase in title for phrase in (
        "first quarter results", "second quarter results", "third quarter results",
        "fourth quarter results", "quarterly results", "annual results",
        "earnings beat", "earnings miss", "financial results",
        "一季度业绩", "二季度业绩", "三季度业绩", "年度业绩", "业绩预告",
    )):
        score += 12
    if item.evidence_type in {"财报", "公司公告", "监管政策"}:
        score += 6
    related = {value.upper() for value in item.related_symbols}
    if related == {symbol.upper()}:
        score += 15
    elif len(related) > 1:
        score -= 4
    if item.published_at and event_start <= item.published_at <= event_end:
        score += 5
    elif item.published_at:
        distance = min(abs((item.published_at - event_start).days), abs((item.published_at - event_end).days))
        score -= distance
    if any(term in title for term in ("weekly", "bulls and bears", "盘点", "早报", "晚报")):
        score -= 5
    if any(term in title for term in ("goldman", "analyst", "price target", "分析师", "目标价")):
        score -= 6
    return score
