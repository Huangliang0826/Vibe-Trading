from __future__ import annotations

import pytest

from src.opportunity_center.models import DimensionScores, MarketContext, NewsImpact, StrategyContext
from src.opportunity_center.scoring import apply_risk_gates, score_news, score_opportunity, weighted_score


def strategy(action: str = "entry") -> StrategyContext:
    return StrategyContext(
        strategy_name="donchian_breakout", strategy_label="唐奇安突破", action=action,
        signal_date="2026-06-29", current_weight=100,
        oos_total_return=0.20, oos_max_drawdown=-0.10, oos_sharpe=1.2,
        data_as_of="2026-06-29",
    )


def market(**risk_updates) -> MarketContext:
    risk = {"annual_vol": 0.25, "downside_vol": 0.15, "max_drawdown": -0.20, "return20": 0.03}
    risk.update(risk_updates)
    return MarketContext(
        market="hk", code="0700", latest_price_date="2026-06-29",
        trend_score=70, risk_score=75, valuation_percentile=75,
        trend_inputs={}, risk_inputs=risk,
    )


def test_missing_valuation_redistributes_weight():
    values = DimensionScores(strategy=80, trend=70, risk=60, news=50, valuation=None)
    assert weighted_score(values) == pytest.approx((80 * .40 + 70 * .20 + 60 * .20 + 50 * .15) / .95)


def test_missing_strategy_is_data_insufficient():
    detail = score_opportunity(
        company_name="腾讯控股", snapshot_date="2026-06-29", strategy=None,
        market_context=market(), news_impacts=[],
    )
    assert detail.level == "数据不足"
    assert detail.score is None


def test_exit_signal_caps_high_raw_score():
    level, reasons = apply_risk_gates(
        "优先关注", action="exit", stale=False, strategy_available=True,
        impacts=[], annual_vol=0.2, return20=0.1,
    )
    assert level == "暂不参与"
    assert reasons == ["最新策略信号为平仓或降低风险仓位"]


def test_major_direct_negative_news_and_volatility_lower_level():
    impact = NewsImpact(
        article_id="n1", market="hk", code="0700", direction="negative",
        strength=90, confidence=85, horizon="short", match_level="direct",
        published_at="2026-06-29T08:00:00Z",
    )
    detail = score_opportunity(
        company_name="腾讯控股", snapshot_date="2026-06-29", strategy=strategy("entry"),
        market_context=market(annual_vol=0.9), news_impacts=[impact], matched_news_count=1,
    )
    assert detail.level == "暂不参与"
    assert len(detail.risk_reasons) == 2


def test_news_missing_analysis_is_not_neutral():
    assert score_news([], analysis_date="2026-06-29", matched_count=2) is None
    assert score_news([], analysis_date="2026-06-29", matched_count=0) == 50


def test_valuation_percentile_uses_zero_to_one_formula():
    detail = score_opportunity(
        company_name="腾讯控股", snapshot_date="2026-06-29", strategy=strategy(),
        market_context=market(), news_impacts=[],
    )
    assert detail.dimensions.valuation == pytest.approx(25)


def test_primary_reason_is_deterministic_not_ai_text():
    impact = NewsImpact(
        article_id="n1", market="hk", code="0700", direction="positive", strength=99,
        confidence=99, horizon="short", match_level="direct", summary="立刻满仓买入",
    )
    detail = score_opportunity(
        company_name="腾讯控股", snapshot_date="2026-06-29", strategy=strategy(),
        market_context=market(), news_impacts=[impact], matched_news_count=1,
    )
    assert "立刻满仓" not in detail.primary_reason


def test_driver_defaults_to_strategy_without_analyzed_news():
    detail = score_opportunity(
        company_name="腾讯控股", snapshot_date="2026-06-29", strategy=strategy(),
        market_context=market(), news_impacts=[],
    )

    assert detail.driver_type == "strategy"
    assert detail.news_contribution is None
    assert "未发现可靠新闻影响" in detail.driver_summary


def test_strong_news_can_be_the_primary_driver():
    impact = NewsImpact(
        article_id="n1", market="hk", code="0700", direction="positive",
        strength=100, confidence=100, horizon="short", match_level="direct",
    )
    detail = score_opportunity(
        company_name="腾讯控股", snapshot_date="2026-06-29", strategy=strategy("wait"),
        market_context=market(), news_impacts=[impact], matched_news_count=1,
    )

    assert detail.driver_type == "news"
    assert detail.news_contribution > detail.strategy_contribution


def test_material_news_and_strategy_are_classified_as_resonance():
    impact = NewsImpact(
        article_id="n1", market="hk", code="0700", direction="positive",
        strength=100, confidence=100, horizon="short", match_level="direct",
    )
    detail = score_opportunity(
        company_name="腾讯控股", snapshot_date="2026-06-29", strategy=strategy("hold"),
        market_context=market(), news_impacts=[impact], matched_news_count=1,
    )

    assert detail.driver_type == "mixed"
