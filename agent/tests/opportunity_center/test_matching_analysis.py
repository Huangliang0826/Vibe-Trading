from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.opportunity_center.models import StockContext
from src.opportunity_center.storage import OpportunityStore


def make_article(
    article_id: str,
    title: str,
    *,
    published_at: str = "2026-06-29T08:00:00Z",
    summary: str = "",
):
    from src.opportunity_center.models import NewsArticle

    return NewsArticle(
        article_id=article_id,
        source="Example Source",
        title=title,
        url=f"https://example.com/{article_id}",
        published_at=published_at,
        summary=summary,
    )


def make_match(article, *, level: str, confidence: float):
    from src.opportunity_center.matching import NewsMatch

    return NewsMatch(article=article, match_level=level, confidence=confidence)


def make_context() -> StockContext:
    return StockContext(
        market="us",
        code="NVDA",
        company_name="NVIDIA Corporation",
        aliases=["NVIDIA", "英伟达"],
        brands=["CUDA"],
        products=["Blackwell"],
        sector="Technology",
        industry="Semiconductors",
    )


def test_build_stock_context_uses_symbol_quote_name_and_profile_fields():
    from src.opportunity_center.matching import build_stock_context

    context = build_stock_context(
        "us",
        "NVDA",
        "NVIDIA Corporation",
        {
            "shortName": "NVIDIA",
            "longName": "NVIDIA Corporation",
            "displayName": "NVIDIA",
            "sector": "Technology",
            "industry": "Semiconductors",
            "brands": ["GeForce", "CUDA"],
            "products": "Blackwell, DGX Cloud",
        },
    )

    assert context.market == "us"
    assert context.code == "NVDA"
    assert context.company_name == "NVIDIA Corporation"
    assert "NVDA" in context.aliases
    assert "NVIDIA" in context.aliases
    assert context.brands == ["GeForce", "CUDA"]
    assert context.products == ["Blackwell", "DGX Cloud"]
    assert context.sector == "Technology"
    assert context.industry == "Semiconductors"


def test_matching_priority_and_confidence():
    from src.opportunity_center.matching import match_articles

    context = make_context()
    matches = match_articles(
        context,
        [
            make_article("a1", "NVIDIA Blackwell demand rises"),
            make_article("a2", "Semiconductor cycle improves"),
            make_article("a3", "Federal Reserve holds rates"),
        ],
    )

    assert [match.match_level for match in matches] == ["direct", "industry", "macro"]
    assert matches[0].confidence > matches[1].confidence > matches[2].confidence


@pytest.mark.parametrize(
    ("ticker", "unrelated_title"),
    [
        ("ON", "Conditions improve for retailers"),
        ("AI", "Retail sales gain after holiday"),
        ("IT", "Profits climb for grocers"),
        ("CAT", "Education spending expands"),
        ("RATES", "Corporate outlook improves"),
    ],
)
def test_short_ascii_tickers_require_token_boundaries(ticker, unrelated_title):
    from src.opportunity_center.matching import match_articles

    context = StockContext(
        market="us",
        code=ticker,
        company_name="Example Holdings",
        aliases=[],
        brands=[],
        products=[],
        sector="",
        industry="",
    )

    assert match_articles(context, [make_article("embedded", unrelated_title)]) == []
    exact = match_articles(context, [make_article("exact", f"{ticker}: shares rise")])
    assert [match.match_level for match in exact] == ["direct"]


@pytest.mark.parametrize(
    ("alias", "unrelated_title"),
    [
        ("ON", "Conditions improve for retailers"),
        ("AI", "Retail sales gain after holiday"),
        ("IT", "Profits climb for grocers"),
        ("CAT", "Education spending expands"),
    ],
)
def test_short_ascii_aliases_require_token_boundaries(alias, unrelated_title):
    from src.opportunity_center.matching import match_articles

    context = StockContext(
        market="us",
        code="EXMPL",
        company_name="Example Holdings",
        aliases=[alias],
        brands=[],
        products=[],
        sector="",
        industry="",
    )

    assert match_articles(context, [make_article("embedded", unrelated_title)]) == []
    exact = match_articles(context, [make_article("exact", f"({alias}) shares rise")])
    assert [match.match_level for match in exact] == ["direct"]


class StubLLM:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = 0
        self.batch_sizes: list[int] = []
        self.seen_article_ids: list[list[str]] = []

    def chat(self, messages, tools=None, timeout=None):
        self.calls += 1
        prompt = messages[-1]["content"]
        article_ids = re.findall(r'"article_id"\s*:\s*"([^"]+)"', prompt)
        self.batch_sizes.append(len(article_ids))
        self.seen_article_ids.append(article_ids)
        return SimpleNamespace(content=self.responses.pop(0))


def test_news_analyzer_caches_by_article_stock_date_and_prompt(tmp_path):
    from src.opportunity_center.news_analysis import NEWS_PROMPT_VERSION, NewsAnalyzer

    store = OpportunityStore(tmp_path / "opportunities.db")
    llm = StubLLM(
        [
            json.dumps(
                {
                    "items": [
                        {
                            "article_id": "a1",
                            "direction": "negative",
                            "strength": 85,
                            "confidence": 80,
                            "horizon": "short",
                            "summary": "出口限制扩大",
                            "rationale": "直接影响可销售市场",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )
    analyzer = NewsAnalyzer(store, llm_factory=lambda: llm)
    context = make_context()
    matches = [make_match(make_article("a1", "NVIDIA hit by export restrictions"), level="direct", confidence=0.95)]

    first = analyzer.analyze(context, matches, "2026-06-29")
    second = analyzer.analyze(context, matches, "2026-06-29")

    assert llm.calls == 1
    assert [impact.direction for impact in first] == ["negative"]
    assert [impact.direction for impact in second] == ["negative"]
    cached = store.get_news_analysis("a1", "us", "NVDA", "2026-06-29", NEWS_PROMPT_VERSION)
    assert cached is not None
    assert cached.direction == "negative"


def test_news_analyzer_skips_malformed_output_without_manufactured_neutral(tmp_path, caplog):
    from src.opportunity_center.news_analysis import NEWS_PROMPT_VERSION, NewsAnalyzer

    store = OpportunityStore(tmp_path / "opportunities.db")
    llm = StubLLM(["```json\nnot valid json\n```"])
    analyzer = NewsAnalyzer(store, llm_factory=lambda: llm)
    matches = [make_match(make_article("a1", "NVIDIA hit by export restrictions"), level="direct", confidence=0.95)]

    impacts = analyzer.analyze(make_context(), matches, "2026-06-29")

    assert impacts == []
    assert llm.calls == 1
    assert "malformed" in caplog.text.lower()
    assert store.get_news_analysis("a1", "us", "NVDA", "2026-06-29", NEWS_PROMPT_VERSION) is None


def test_news_analyzer_caps_selection_and_batches_by_priority(tmp_path):
    from src.opportunity_center.news_analysis import NewsAnalyzer

    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    direct_matches = [
        make_match(
            make_article(
                f"d{i}",
                f"NVIDIA headline {i}",
                published_at=(now - timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
            ),
            level="direct",
            confidence=0.95,
        )
        for i in range(14)
    ]
    industry_matches = [
        make_match(
            make_article(
                f"i{i}",
                f"Semiconductor headline {i}",
                published_at=(now - timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
            ),
            level="industry",
            confidence=0.65,
        )
        for i in range(7)
    ]
    macro_matches = [
        make_match(
            make_article(
                f"m{i}",
                f"Federal Reserve headline {i}",
                published_at=(now - timedelta(days=i)).isoformat().replace("+00:00", "Z"),
            ),
            level="macro",
            confidence=0.35,
        )
        for i in range(4)
    ]

    llm = StubLLM(
        [
            json.dumps(
                {
                    "items": [
                        {
                            "article_id": article_id,
                            "direction": "positive",
                            "strength": 70,
                            "confidence": 60,
                            "horizon": "short",
                            "summary": f"{article_id} summary",
                            "rationale": f"{article_id} rationale",
                        }
                        for article_id in batch
                    ]
                },
                ensure_ascii=False,
            )
            for batch in [
                [match.article.article_id for match in (direct_matches[:10] + industry_matches[:2])],
                [match.article.article_id for match in (industry_matches[2:5] + macro_matches[:3])],
            ]
        ]
    )
    analyzer = NewsAnalyzer(OpportunityStore(tmp_path / "opportunities.db"), llm_factory=lambda: llm)

    impacts = analyzer.analyze(make_context(), direct_matches + industry_matches + macro_matches, "2026-06-29")

    assert len(impacts) == 18
    assert llm.calls == 2
    assert llm.batch_sizes == [12, 6]
    assert llm.seen_article_ids == [
        [match.article.article_id for match in (direct_matches[:10] + industry_matches[:2])],
        [match.article.article_id for match in (industry_matches[2:5] + macro_matches[:3])],
    ]
    assert [impact.article_id for impact in impacts[:3]] == ["d0", "d1", "d2"]
