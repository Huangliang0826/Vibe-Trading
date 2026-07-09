"""AI daily digest via Volcengine Ark (Doubao) with server-side web search.

Replaces the mechanical template summary for 今日投资简报 / 今日重大新闻 with a
model-written briefing sourced purely from Ark's built-in ``web_search`` tool
(the site's collected articles are NOT fed into the prompt). Chinese only —
the English tab keeps the original template digest. Results are cached per
(date, language) by the caller — this module only speaks to the API.
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

    def generate(self, prompt: str) -> str:
        """One-shot responses call with web_search enabled; returns output text."""
        if not self.api_key:
            raise ArkDigestError("ARK_API_KEY 未配置（请写入 ~/.vibe-trading/.env）")
        payload = {
            "model": self.model,
            "input": [{"role": "user", "content": prompt}],
            "tools": [{"type": "web_search", "max_keyword": 2}],
        }
        try:
            response = httpx.post(
                f"{self.base_url}/responses",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=_TIMEOUT_SECONDS,
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
    """Chinese-only prompt asking for a web-searched briefing + major-news JSON."""
    return (
        f"你是严谨的投资新闻编辑。今天是 {date_key}。请用联网搜索获取当日重要财经与科技动态"
        "（覆盖宏观政策、A股/港股/美股大盘与行业、大宗商品与汇率、重要公司事件），完成两件事：\n"
        "1. briefing：写一段 120~200 字的当日投资简报，概括对投资者最重要的主线（宏观、行业、个股），"
        "语气克制、只陈述事实与直接影响，不编造数字或消息，不给买卖建议。\n"
        "2. major：挑选 6~8 条当日最重大的新闻，每条给出简短标题 title、40~80 字摘要 summary、"
        "以及对市场的影响 impact（positive=利好 / negative=利空 / neutral=中性）。\n"
        "全部输出使用简体中文。\n"
        '只返回一个 JSON 对象，不要 Markdown 代码块：{"briefing":"...",'
        '"major":[{"title":"...","summary":"...","impact":"positive|negative|neutral"}]}'
    )


def parse_digest_output(text: str) -> tuple[str, list[dict[str, str]]]:
    """Parse the model's JSON into (briefing, major items); raise if unusable."""
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
        title = str(row.get("title", "")).strip()
        if not title:
            continue
        impact = str(row.get("impact", "neutral")).strip().lower()
        if impact not in {"positive", "negative", "neutral"}:
            impact = "neutral"
        major.append({
            "title": title,
            "summary": str(row.get("summary", "")).strip(),
            "impact": impact,
        })
    return briefing, major
