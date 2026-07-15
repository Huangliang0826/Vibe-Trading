"""AI daily digest via Volcengine Ark (Doubao).

The fast path summarizes articles already collected by the news center. A
second background pass can use Ark's ``web_search`` tool to verify and enrich
the briefing without blocking the page.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

ARK_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_DEFAULT_MODEL = "doubao-seed-2-1-pro-260628"
_TIMEOUT_SECONDS = 300.0  # pro model + web search regularly exceeds two minutes
_FAST_TIMEOUT_SECONDS = 30.0  # the synchronous path must fail over quickly

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class ArkDigestError(RuntimeError):
    """Raised when the Ark digest call fails or returns unusable output."""


def _ensure_project_env() -> None:
    """Load the project .env chain (~/.vibe-trading/.env first) if not yet done."""
    try:
        from src.providers.llm import _ensure_dotenv

        _ensure_dotenv()
    except Exception:  # noqa: BLE001 — env loading is best-effort; getenv falls through
        pass


class ArkDigestClient:
    """Minimal Ark ``responses`` API client (httpx, no SDK dependency)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        # Env vars are resolved lazily in generate(): at construction time
        # (module registration) the project .env may not be loaded yet.
        self._api_key_override = api_key
        self.base_url = (base_url or os.getenv("ARK_BASE_URL") or ARK_DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.getenv("ARK_MODEL") or ARK_DEFAULT_MODEL

    @property
    def api_key(self) -> str:
        if self._api_key_override is not None:
            return self._api_key_override
        _ensure_project_env()
        return os.getenv("ARK_API_KEY", "")

    def generate(self, prompt: str, *, web_search: bool = True) -> str:
        """One-shot responses call, optionally enabling server-side web search."""
        if not self.api_key:
            raise ArkDigestError("ARK_API_KEY 未配置（请写入 ~/.vibe-trading/.env）")
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [{"role": "user", "content": prompt}],
        }
        if web_search:
            payload["tools"] = [{"type": "web_search", "max_keyword": 1}]
        try:
            response = httpx.post(
                f"{self.base_url}/responses",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=_TIMEOUT_SECONDS if web_search else _FAST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:200]
            raise ArkDigestError(f"Ark 接口返回 {exc.response.status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ArkDigestError(f"Ark 接口请求失败: {exc}") from exc
        text = extract_output_text(response.json())
        if not text.strip():
            raise ArkDigestError("Ark 返回内容为空")
        return text


def extract_output_text(data: Any) -> str:
    """Collect assistant text from an Ark/OpenAI responses payload.

    Tolerates both the convenience ``output_text`` field and the canonical
    ``output`` item list (message → content → output_text) so minor API-shape
    drift does not break the digest.
    """
    if not isinstance(data, dict):
        return ""
    convenience = data.get("output_text")
    if isinstance(convenience, str) and convenience.strip():
        return convenience
    chunks: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if isinstance(content, str):
            chunks.append(content)
            continue
        for part in content or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                chunks.append(str(part.get("text", "")))
    return "\n".join(chunk for chunk in chunks if chunk)


def build_digest_prompt(date_key: str) -> str:
    """Ask Ark directly for today's web-searched investment briefing."""
    return (
        f"今天是 {date_key}（北京时间）。请联网搜索并总结今天最重要的金融、科技和地缘政治新闻。"
        "用简体中文把今日投资简报分成三个部分：地缘政治、金融、科技。"
        "每部分不超过 190 字，说明最重要的事件及其对市场的直接影响。"
        "只写当天能够确认的事实，不编造信息，不给出买卖建议。"
        '只返回 JSON，不要 Markdown：{"geopolitics":"...","finance":"...","technology":"..."}'
    )


def parse_structured_briefing_output(text: str) -> str:
    """Normalize Ark's three briefing sections into display-ready lines."""
    try:
        parsed = json.loads(_FENCE_RE.sub("", text).strip())
    except json.JSONDecodeError as exc:
        raise ArkDigestError(f"Ark 返回的不是有效 JSON: {text[:120]}") from exc
    if not isinstance(parsed, dict):
        raise ArkDigestError("Ark 返回的 JSON 不是对象")
    sections = [
        ("地缘政治", "geopolitics"),
        ("金融", "finance"),
        ("科技", "technology"),
    ]
    lines: list[str] = []
    for label, key in sections:
        value = re.sub(r"\s+", " ", str(parsed.get(key) or "")).strip()[:190]
        if not value:
            raise ArkDigestError(f"Ark 返回缺少 {key}")
        lines.append(f"{label}：{value}")
    return "\n".join(lines)


def build_local_digest_prompt(date_key: str, articles: list[dict[str, str]]) -> str:
    """Build a fast summarization prompt from already collected daily articles."""
    rows = []
    for index, article in enumerate(articles[:25], start=1):
        title = str(article.get("title") or "").strip()[:180]
        summary = str(article.get("summary") or "").strip()[:260]
        source = str(article.get("source") or "").strip()[:60]
        rows.append(f"{index}. [{source}] {title}\n   {summary}")
    article_text = "\n".join(rows) or "（当天暂未收录新闻）"
    return (
        f"你是严谨的投资新闻编辑。以下是新闻中心在 {date_key} 已收录的当日新闻。"
        "只依据给定材料生成简体中文投资简报，不进行联网搜索，不补充材料中没有的事实或数字。\n"
        "输出一段 300 字以内的 briefing，并选出最多 6 条重大新闻 major。每条包含 title、"
        "40~80 字 summary 和 impact（positive/negative/neutral）。\n"
        '只返回 JSON：{"briefing":"...","major":[{"title":"...","summary":"...",'
        '"impact":"positive|negative|neutral"}]}\n\n新闻列表：\n'
        f"{article_text}"
    )


def build_web_enrichment_prompt(
    date_key: str,
    local_briefing: str,
    articles: list[dict[str, str]],
) -> str:
    """Build a focused web-verification prompt anchored by the local digest."""
    headlines = "\n".join(
        f"- {str(row.get('title') or '').strip()[:180]}"
        for row in articles[:10]
        if str(row.get("title") or "").strip()
    )
    return (
        f"你是严谨的投资新闻编辑。今天是 {date_key}（北京时间）。下面已有一份基于本地新闻源的简报。"
        "请联网核实其中最重要的事件，并只补充当天确实发生、对市场有直接影响的重大财经或科技新闻。"
        "不要重新进行泛化的全市场搜索；无法确认日期的内容不要收录。\n"
        f"本地简报：{local_briefing}\n候选标题：\n{headlines}\n"
        "返回 600 字以内的 briefing 和最多 6 条 major；每条包含 title、summary、news_date、impact。"
        f"news_date 必须为 {date_key}。"
        '只返回 JSON：{"briefing":"...","major":[{"title":"...","summary":"...",'
        '"news_date":"YYYY-MM-DD","impact":"positive|negative|neutral"}]}'
    )


def build_fallback_digest(
    date_key: str,
    articles: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    """Build a deterministic digest when the fast Ark request is unavailable.

    The fallback deliberately uses only already-collected article fields.  It
    gives the page useful content immediately while the web-enrichment task
    retries Ark in the background.
    """
    usable = [row for row in articles if str(row.get("title") or "").strip()]
    if not usable:
        return (
            f"{date_key} 当日暂无足够的已收录中文新闻，正在后台联网核实。",
            [],
        )
    titles = "；".join(str(row["title"]).strip() for row in usable[:3])
    briefing = (
        f"{date_key} 已收录 {len(usable)} 条中文新闻。重点关注：{titles}。"
        "以上为基于已收录来源生成的本地摘要，联网核实将在后台继续。"
    )
    major = [
        {
            "title": str(row["title"]).strip()[:120],
            "summary": re.sub(r"\s+", " ", str(row.get("summary") or "")).strip()[:160],
            "impact": str(row.get("impact") or "neutral"),
        }
        for row in usable[:6]
    ]
    return briefing, major


def parse_digest_output(text: str, date_key: str | None = None) -> tuple[str, list[dict[str, str]]]:
    """Parse the model's JSON into (briefing, major items); raise if unusable.

    When ``date_key`` is given, major items whose self-reported ``news_date``
    names a different day are dropped — a second line of defence against web
    search surfacing yesterday's headlines as today's. Items without a
    ``news_date`` are kept (older cache entries and imperfect model output
    should degrade gracefully, not vanish).
    """
    try:
        parsed = json.loads(_FENCE_RE.sub("", text).strip())
    except json.JSONDecodeError as exc:
        raise ArkDigestError(f"Ark 返回的不是有效 JSON: {text[:120]}") from exc
    if not isinstance(parsed, dict):
        raise ArkDigestError("Ark 返回的 JSON 不是对象")
    briefing = str(parsed.get("briefing", "")).strip()
    if not briefing:
        raise ArkDigestError("Ark 返回缺少 briefing")
    major: list[dict[str, str]] = []
    for row in parsed.get("major") or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()[:120]
        if not title:
            continue
        news_date = str(row.get("news_date", "")).strip()
        if date_key and news_date and news_date != date_key:
            continue
        impact = str(row.get("impact", "neutral")).strip().lower()
        if impact not in {"positive", "negative", "neutral"}:
            impact = "neutral"
        major.append({
            "title": title,
            "summary": re.sub(r"\s+", " ", str(row.get("summary", ""))).strip()[:160],
            "impact": impact,
        })
        if len(major) >= 6:
            break
    return briefing, major
