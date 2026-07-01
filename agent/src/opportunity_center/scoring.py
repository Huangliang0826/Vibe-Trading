"""Deterministic opportunity scoring and risk gates."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Iterable

from src.opportunity_center.models import (
    SCORE_VERSION,
    STRATEGY_VERSION,
    DimensionScores,
    MarketContext,
    NewsImpact,
    OpportunityDetail,
    OpportunityDriver,
    OpportunityLevel,
    StrategyContext,
)

WEIGHTS = {"strategy": 0.40, "trend": 0.20, "risk": 0.20, "news": 0.15, "valuation": 0.05}
ACTION_BASE = {"entry": 90.0, "add": 85.0, "hold": 72.0, "wait": 45.0, "exit": 20.0, "risk_exit": 10.0, "none": 40.0}
MATCH_WEIGHTS = {"direct": 1.0, "industry": 0.4, "macro": 0.2}
LEVEL_ORDER: list[OpportunityLevel] = ["暂不参与", "值得观察", "优先关注"]


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(float(value), upper))


def score_strategy(context: StrategyContext | None) -> float | None:
    if context is None or context.oos_sharpe is None or context.oos_total_return is None or context.oos_max_drawdown is None:
        return None
    quality = clamp(50 + 20 * context.oos_sharpe + 40 * context.oos_total_return + 50 * context.oos_max_drawdown)
    return clamp(0.70 * ACTION_BASE[context.action] + 0.30 * quality)


def score_trend(context: MarketContext | None) -> float | None:
    return None if context is None else context.trend_score


def score_risk(context: MarketContext | None) -> float | None:
    return None if context is None else context.risk_score


def score_news(impacts: Iterable[NewsImpact], *, analysis_date: str, matched_count: int = 0) -> float | None:
    rows = list(impacts)
    if not rows:
        return None if matched_count else 50.0
    target_date = date.fromisoformat(analysis_date[:10])
    numerator = 0.0
    denominator = 0.0
    signs = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}
    for impact in rows:
        if impact.strength is None or impact.confidence is None:
            continue
        age_days = 0
        if impact.published_at:
            try:
                published = datetime.fromisoformat(impact.published_at.replace("Z", "+00:00")).date()
                age_days = max((target_date - published).days, 0)
            except ValueError:
                age_days = 0
        weight = MATCH_WEIGHTS[impact.match_level] * math.exp(-age_days / 3.0)
        signed_strength = signs[impact.direction] * impact.strength * (impact.confidence / 100.0)
        numerator += signed_strength * weight
        denominator += weight
    if denominator == 0:
        return None if matched_count else 50.0
    return clamp(50 + (numerator / denominator) / 2.0)


def score_valuation(context: MarketContext | None) -> float | None:
    if context is None or context.valuation_percentile is None:
        return None
    percentile = context.valuation_percentile / 100.0 if context.valuation_percentile > 1 else context.valuation_percentile
    return clamp(100 * (1 - percentile))


def weighted_score(values: DimensionScores) -> float | None:
    pairs = [(WEIGHTS[name], getattr(values, name)) for name in WEIGHTS if getattr(values, name) is not None]
    if not pairs:
        return None
    total_weight = sum(weight for weight, _ in pairs)
    return sum(weight * float(value) for weight, value in pairs) / total_weight


def apply_risk_gates(
    level: OpportunityLevel,
    *,
    action: str,
    stale: bool,
    strategy_available: bool,
    impacts: Iterable[NewsImpact],
    annual_vol: float | None,
    return20: float | None,
) -> tuple[OpportunityLevel, list[str]]:
    reasons: list[str] = []
    if stale or not strategy_available:
        reasons.append("价格数据过期" if stale else "策略样本外结果不可用")
        return "数据不足", reasons
    if action in {"exit", "risk_exit"}:
        level = "暂不参与"
        reasons.append("最新策略信号为平仓或降低风险仓位")
    major_negative = any(
        item.match_level == "direct"
        and item.direction == "negative"
        and (item.strength or 0) >= 80
        and (item.confidence or 0) >= 75
        for item in impacts
    )
    if major_negative:
        level = _lower_level(level)
        reasons.append("存在高可信度重大个股利空")
    if (annual_vol is not None and annual_vol >= 0.80) or (return20 is not None and return20 <= -0.20):
        level = _lower_level(level)
        reasons.append("近期波动或跌幅触发风险降级")
    return level, reasons


def score_opportunity(
    *,
    company_name: str,
    snapshot_date: str,
    strategy: StrategyContext | None,
    market_context: MarketContext,
    news_impacts: list[NewsImpact],
    matched_news_count: int = 0,
    previous_score: float | None = None,
    stale: bool = False,
    history_available: bool = False,
) -> OpportunityDetail:
    dimensions = DimensionScores(
        strategy=score_strategy(strategy),
        trend=score_trend(market_context),
        risk=score_risk(market_context),
        news=score_news(news_impacts, analysis_date=snapshot_date, matched_count=matched_news_count),
        valuation=score_valuation(market_context),
    )
    missing = [name for name in WEIGHTS if getattr(dimensions, name) is None]
    strategy_available = dimensions.strategy is not None
    raw_score = weighted_score(dimensions) if strategy_available and not stale else None
    level: OpportunityLevel
    if raw_score is None:
        level = "数据不足"
    elif raw_score >= 75:
        level = "优先关注"
    elif raw_score >= 55:
        level = "值得观察"
    else:
        level = "暂不参与"
    action = strategy.action if strategy else "none"
    risk_inputs = market_context.risk_inputs
    level, gate_reasons = apply_risk_gates(
        level,
        action=action,
        stale=stale,
        strategy_available=strategy_available,
        impacts=news_impacts,
        annual_vol=_optional_float(risk_inputs.get("annual_vol")),
        return20=_optional_float(risk_inputs.get("return20")),
    )
    primary_reason = _primary_reason(dimensions)
    driver_type, driver_summary, strategy_contribution, news_contribution = _driver_attribution(
        dimensions, strategy, news_impacts,
    )
    explanations = _dimension_explanations(dimensions) + gate_reasons
    score = round(raw_score, 4) if raw_score is not None else None
    return OpportunityDetail(
        market=market_context.market,
        code=market_context.code,
        company_name=company_name,
        snapshot_date=snapshot_date,
        score=score,
        score_change=round(score - previous_score, 4) if score is not None and previous_score is not None else None,
        level=level,
        latest_action=action,
        signal_date=strategy.signal_date if strategy else None,
        strategy_name=strategy.strategy_name if strategy else None,
        strategy_label=strategy.strategy_label if strategy else None,
        primary_reason=primary_reason,
        driver_type=driver_type,
        driver_summary=driver_summary,
        strategy_contribution=strategy_contribution,
        news_contribution=news_contribution,
        risk_reasons=gate_reasons,
        dimensions=dimensions,
        data_as_of=market_context.latest_price_date,
        stale=stale,
        degraded=bool(missing),
        missing_dimensions=missing,
        score_version=SCORE_VERSION,
        strategy_version=STRATEGY_VERSION,
        news=news_impacts,
        explanations=explanations,
        history_available=history_available,
    )


def _lower_level(level: OpportunityLevel) -> OpportunityLevel:
    if level == "数据不足":
        return level
    index = LEVEL_ORDER.index(level)
    return LEVEL_ORDER[max(index - 1, 0)]


def _primary_reason(values: DimensionScores) -> str:
    labels = {"strategy": "策略信号", "trend": "趋势状态", "risk": "风险质量", "news": "新闻影响", "valuation": "估值状态"}
    available = [(name, float(getattr(values, name))) for name in WEIGHTS if getattr(values, name) is not None]
    if not available:
        return "有效数据不足，暂不形成机会判断"
    name, value = max(available, key=lambda pair: abs((pair[1] - 50) * WEIGHTS[pair[0]]))
    direction = "提供主要正贡献" if value >= 50 else "构成主要拖累"
    return f"{labels[name]}{direction}"


def _dimension_explanations(values: DimensionScores) -> list[str]:
    labels = {"strategy": "策略", "trend": "趋势", "risk": "风险", "news": "新闻", "valuation": "估值"}
    return [
        f"{labels[name]}评分 {float(getattr(values, name)):.1f}"
        for name in WEIGHTS
        if getattr(values, name) is not None
    ]


def _driver_attribution(
    values: DimensionScores,
    strategy: StrategyContext | None,
    impacts: list[NewsImpact],
) -> tuple[OpportunityDriver, str, float | None, float | None]:
    strategy_contribution = (
        round(abs((values.strategy - 50) * WEIGHTS["strategy"]), 2)
        if values.strategy is not None else None
    )
    has_reliable_news = any(
        impact.strength is not None and impact.confidence is not None
        for impact in impacts
    )
    news_contribution = (
        round(abs((values.news - 50) * WEIGHTS["news"]), 2)
        if has_reliable_news and values.news is not None else None
    )
    strategy_value = strategy_contribution or 0.0
    news_value = news_contribution or 0.0
    strategy_label = strategy.strategy_label if strategy and strategy.strategy_label else "量化策略"

    if not has_reliable_news:
        return (
            "strategy",
            f"未发现可靠新闻影响，主要由{strategy_label}信号与量化评分驱动。",
            strategy_contribution,
            None,
        )
    if news_value >= max(strategy_value * 1.25, 0.01):
        return (
            "news",
            f"新闻贡献 {news_value:.2f}，超过策略贡献 {strategy_value:.2f}，本次机会主要由新闻事件驱动。",
            strategy_contribution,
            news_contribution,
        )
    if news_value >= max(strategy_value * 0.60, 0.01):
        return (
            "mixed",
            f"策略贡献 {strategy_value:.2f}、新闻贡献 {news_value:.2f}，两类信号形成共振。",
            strategy_contribution,
            news_contribution,
        )
    return (
        "strategy",
        f"策略贡献 {strategy_value:.2f} 高于新闻贡献 {news_value:.2f}，本次机会仍以{strategy_label}信号为主。",
        strategy_contribution,
        news_contribution,
    )


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
