from datetime import date

import pandas as pd

import src.historical_events.evidence as evidence_module
from src.historical_events.evidence import AlpacaNewsProvider, EastMoneyNewsProvider, EvidenceSearcher
from src.historical_events.models import EvidenceItem


class FakeProvider:
    def __init__(self, items: list[EvidenceItem]) -> None:
        self.items = items
        self.calls: list[tuple[str, str, date, date]] = []

    def search(self, symbol: str, company_name: str, start: date, end: date) -> list[EvidenceItem]:
        self.calls.append((symbol, company_name, start, end))
        return self.items


def item(
    title: str, published_at: str, source: str, url: str = "https://example.com",
    related_symbols: list[str] | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        title=title, url=url, source=source, published_at=published_at,
        snippet="事件摘要", evidence_type="财经新闻", related_symbols=related_symbols or [],
    )


def test_hk_uses_eastmoney_provider_and_keeps_only_event_window():
    eastmoney = FakeProvider([
        item("腾讯控股发布业绩", "2024-05-14", "东方财富"),
        item("腾讯控股旧闻", "2024-06-20", "东方财富"),
    ])
    alpaca = FakeProvider([])
    searcher = EvidenceSearcher(hk_provider=eastmoney, us_provider=alpaca)

    evidence = searcher.search("hk", "00700", "腾讯控股", date(2024, 5, 14), date(2024, 5, 16))

    assert [row.title for row in evidence] == ["腾讯控股发布业绩"]
    assert len(eastmoney.calls) == 1
    assert alpaca.calls == []


def test_us_uses_alpaca_provider_not_hk_provider():
    eastmoney = FakeProvider([])
    alpaca = FakeProvider([
        item("Weekly bulls and bears includes NVIDIA", "2024-05-16", "Benzinga"),
        item("Goldman raises NVIDIA forecast after earnings", "2024-05-16", "Benzinga"),
        item("Qualcomm Shares Rise On NVIDIA's Earnings Beat", "2024-05-15", "Benzinga", related_symbols=["QCOM", "NVDA"]),
        item("Nvidia's First Quarter Results Confirm Strong Growth", "2024-05-15", "Benzinga", related_symbols=["NVDA"]),
    ])
    searcher = EvidenceSearcher(hk_provider=eastmoney, us_provider=alpaca)

    evidence = searcher.search("us", "NVDA", "NVDA", date(2024, 5, 14), date(2024, 5, 16))

    assert [row.title for row in evidence] == [
        "Nvidia's First Quarter Results Confirm Strong Growth",
        "Qualcomm Shares Rise On NVIDIA's Earnings Beat",
        "Goldman raises NVIDIA forecast after earnings",
        "Weekly bulls and bears includes NVIDIA",
    ]
    assert len(alpaca.calls) == 1
    assert eastmoney.calls == []


def test_unknown_market_has_no_generic_web_fallback():
    searcher = EvidenceSearcher(hk_provider=FakeProvider([]), us_provider=FakeProvider([]))

    assert searcher.search("cn", "600519", "贵州茅台", date(2024, 5, 14), date(2024, 5, 16)) == []


def test_eastmoney_converts_finance_rows_and_rejects_unrelated_titles():
    def fetcher(symbol: str) -> pd.DataFrame:
        return pd.DataFrame([
            {"新闻标题": "腾讯控股发布季度业绩", "新闻内容": "利润增长", "发布时间": "2024-05-14 18:00:00", "文章来源": "证券时报", "新闻链接": "https://finance.eastmoney.com/a/1.html"},
            {"新闻标题": "港股公告精选", "新闻内容": "正文顺带提到腾讯控股", "发布时间": "2024-05-14 12:00:00", "文章来源": "东方财富", "新闻链接": "https://finance.eastmoney.com/a/2.html"},
        ])

    evidence = EastMoneyNewsProvider(fetcher=fetcher).search(
        "00700", "腾讯控股", date(2024, 5, 11), date(2024, 5, 18),
    )

    assert [row.title for row in evidence] == ["腾讯控股发布季度业绩"]
    assert evidence[0].published_at.isoformat() == "2024-05-14"


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "news": [
                {"headline": "NVIDIA announces results", "summary": "Revenue beats estimates", "created_at": "2024-05-15T20:00:00Z", "source": "benzinga", "url": "https://example.com/nvda", "symbols": ["NVDA"]},
                {"headline": "Apple update", "summary": "Unrelated", "created_at": "2024-05-15T20:00:00Z", "source": "benzinga", "url": "https://example.com/aapl", "symbols": ["AAPL"]},
            ],
            "next_page_token": None,
        }


class FakeSession:
    def __init__(self) -> None:
        self.params = None

    def get(self, url, *, headers, params, timeout):
        self.params = params
        return FakeResponse()


def test_alpaca_requests_exact_symbol_and_event_window():
    session = FakeSession()
    provider = AlpacaNewsProvider(api_key="key", secret_key="secret", session=session)

    evidence = provider.search("NVDA", "NVIDIA", date(2024, 5, 11), date(2024, 5, 18))

    assert [row.title for row in evidence] == ["NVIDIA announces results"]
    assert session.params["symbols"] == "NVDA"
    assert session.params["start"].startswith("2024-05-11")
    assert session.params["end"].startswith("2024-05-19")


def test_alpaca_credentials_fall_back_to_project_env(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("ALPACA_API_KEY=project-key\nALPACA_SECRET_KEY=project-secret\n", encoding="utf-8")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.setattr(evidence_module, "ALPACA_ENV_PATH", env_path)

    assert evidence_module._alpaca_credentials() == ("project-key", "project-secret")
