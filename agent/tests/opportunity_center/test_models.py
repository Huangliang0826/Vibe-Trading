import pytest
from pydantic import ValidationError

from src.opportunity_center.models import (
    SCORE_VERSION,
    STRATEGY_VERSION,
    MarketContext,
    NewsImpact,
    OpportunityDetail,
    OpportunityItem,
    OpportunityList,
    RefreshJob,
    StockContext,
    StrategyContext,
)


def test_opportunity_item_rejects_score_outside_range():
    with pytest.raises(ValidationError):
        OpportunityItem(
            market="hk",
            code="0700",
            company_name="腾讯控股",
            snapshot_date="2026-06-29",
            score=101,
            level="优先关注",
            data_as_of="2026-06-29",
            score_version="opportunity-v1",
            strategy_version="oos-holdout-v1",
        )


def test_news_impact_uses_closed_direction_vocabulary():
    impact = NewsImpact(
        article_id="a1",
        market="us",
        code="NVDA",
        direction="positive",
        strength=80,
        confidence=75,
        horizon="medium",
        summary="需求改善",
        rationale="订单增长",
    )
    assert impact.direction == "positive"


def test_versions_are_stable_public_contracts():
    assert SCORE_VERSION == "opportunity-v1"
    assert STRATEGY_VERSION == "oos-holdout-v1"


def test_opportunity_detail_and_related_contexts_accept_expected_shapes():
    detail = OpportunityDetail(
        market="hk",
        code="0700",
        company_name="腾讯控股",
        snapshot_date="2026-06-29",
        score=88,
        level="优先关注",
        latest_action="hold",
        data_as_of="2026-06-29",
        score_version=SCORE_VERSION,
        strategy_version=STRATEGY_VERSION,
        news=[
            {
                "article_id": "a1",
                "market": "hk",
                "code": "0700",
                "direction": "positive",
                "strength": 80,
                "confidence": 75,
                "horizon": "medium",
                "summary": "游戏审批改善",
                "rationale": "政策预期回暖",
                "match_level": "industry",
            }
        ],
        explanations=["策略和新闻共振"],
        history_available=True,
    )
    stock = StockContext(
        market="hk",
        code="0700",
        company_name="腾讯控股",
        aliases=["Tencent"],
        brands=["微信"],
        products=["游戏"],
        sector="通信服务",
        industry="互联网内容与信息",
    )
    strategy = StrategyContext(
        strategy_name="quality_momentum",
        strategy_label="收益质量动量",
        action="hold",
        signal_date="2026-06-29",
        current_weight=65,
        oos_total_return=72,
        oos_max_drawdown=18,
        oos_sharpe=61,
    )
    market = MarketContext(
        market="hk",
        code="0700",
        latest_price_date="2026-06-29",
        trend_score=76,
        risk_score=34,
        valuation_percentile=58,
    )

    assert detail.news[0].match_level == "industry"
    assert stock.aliases == ["Tencent"]
    assert strategy.current_weight == 65
    assert market.valuation_percentile == 58


def test_refresh_job_and_list_keep_required_fields():
    listing = OpportunityList(
        items=[],
        latest_success_at="2026-06-29T08:00:00Z",
        active_job=RefreshJob(
            job_id="job-1",
            status="running",
            markets=["hk", "us"],
            trigger="manual",
            completed=2,
            total=4,
            created_at="2026-06-29T08:00:00Z",
            started_at="2026-06-29T08:00:01Z",
            finished_at=None,
            updated_at="2026-06-29T08:03:00Z",
            error=None,
        ),
        last_refresh_error=None,
    )

    assert listing.active_job is not None
    assert listing.active_job.markets == ["hk", "us"]
