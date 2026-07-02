from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.news_center_routes import register_news_center_routes
from src.news_center.models import NewsCenterDigest, NewsCenterList, NewsCenterRefreshResult


class FakeService:
    def list_articles(self, **kwargs):
        self.filters = kwargs
        return NewsCenterList(items=[], total=0, sectors=[])

    def get_dates(self):
        return ["2026-07-01"]

    def get_digest(self, date_key, language="zh"):
        return NewsCenterDigest(
            date=date_key, article_count=0, watchlist_count=0,
            positive_count=0, negative_count=0, summary="暂无", major_items=[],
        )

    def refresh(self):
        return NewsCenterRefreshResult(fetched=1, total=10, latest_date="2026-07-01")


def test_articles_pass_filters_to_service():
    app = FastAPI()
    service = FakeService()
    register_news_center_routes(app, require_auth=lambda: None, service=service)

    response = TestClient(app).get(
        "/news-center/articles?date=2026-07-01&sector=ai&direction=positive&watchlist_only=true&language=zh"
    )

    assert response.status_code == 200
    assert service.filters["date_key"] == "2026-07-01"
    assert service.filters["watchlist_only"] is True
    assert service.filters["language"] == "zh"


def test_digest_and_refresh_contracts():
    app = FastAPI()
    register_news_center_routes(app, require_auth=lambda: None, service=FakeService())
    client = TestClient(app)

    assert client.get("/news-center/digest?date=2026-07-01").status_code == 200
    assert client.post("/news-center/refresh").json()["fetched"] == 1
