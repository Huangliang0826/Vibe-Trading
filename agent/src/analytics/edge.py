"""Edge scorecard: turn stored research-quality metrics into an honest,
net-of-cost, benchmark-relative verdict per signal source.

The question this answers, per source: *after costs, versus a do-nothing
baseline, out of sample — does this signal actually have an edge, and how
confident are we?*

Each source is scored on ONE headline metric:
  - scanner:       top_bottom_spread_pct — a long/short (market-neutral, i.e.
                   already benchmark-relative) forward return. Costs apply.
  - forecast:      directional_accuracy — beat a 50% coin flip? Not a return,
                   so no cost haircut; the baseline (0.5) is the benchmark.
  - paper_trading: sharpe — risk-adjusted return from a backtest that already
                   nets costs. A point estimate (no interval), so weaker.

Verdicts are deliberately conservative: an "edge" requires the whole
confidence interval (after cost) to clear the baseline. If it straddles the
baseline we call it "no_edge" — not demonstrated — rather than pretending.
"""
from __future__ import annotations

from dataclasses import dataclass

from .statistics import wilson_interval

MIN_SAMPLE = 20

# A meaningful backtest Sharpe bar for point-estimate (no-interval) sources.
SHARPE_EDGE_BAR = 0.5


@dataclass(frozen=True)
class EdgeSpec:
    metric: str          # the quality metric_name that represents "edge"
    baseline: float      # null hypothesis / do-nothing benchmark
    is_return: bool      # True → a return, so a cost haircut applies
    unit: str            # "pct" | "accuracy" | "sharpe"
    cost_legs: int       # how many round-trip legs to charge (0 = none)
    label: str           # human label for the headline number


EDGE_SPECS: dict[str, EdgeSpec] = {
    "scanner": EdgeSpec("top_bottom_spread_pct", 0.0, True, "pct", 2, "多空价差 · 扣成本后"),
    "forecast": EdgeSpec("directional_accuracy", 0.5, False, "accuracy", 0, "方向准确率 vs 掷硬币"),
    "paper_trading": EdgeSpec("sharpe", 0.0, False, "sharpe", 0, "夏普比率 · 已扣成本"),
}


@dataclass
class EdgeAssessment:
    verdict: str        # "edge" | "no_edge" | "insufficient"
    confidence: str     # "significant" | "point_estimate" | "insufficient"
    net_value: float | None   # headline value after cost haircut
    net_low: float | None
    net_high: float | None
    cost_applied: float       # cost subtracted (same unit as value), 0 if none


def cost_haircut(spec: EdgeSpec, cost_bps: float) -> float:
    """Cost to subtract, in the metric's own unit (percent for returns)."""
    if not spec.is_return:
        return 0.0
    # bps → percent (20bps = 0.20%), charged per leg.
    return (cost_bps / 100.0) * spec.cost_legs


def evaluate_edge(
    spec: EdgeSpec,
    *,
    value: float | None,
    interval_low: float | None,
    interval_high: float | None,
    sample_count: int,
    cost_bps: float,
) -> EdgeAssessment:
    if value is None or sample_count < MIN_SAMPLE:
        return EdgeAssessment("insufficient", "insufficient", None, None, None, 0.0)

    cost = cost_haircut(spec, cost_bps)
    net = value - cost
    net_low = None if interval_low is None else interval_low - cost
    net_high = None if interval_high is None else interval_high - cost

    if net_low is not None:
        # Interval available → judge significance conservatively.
        if net_low > spec.baseline:
            return EdgeAssessment("edge", "significant", net, net_low, net_high, cost)
        return EdgeAssessment("no_edge", "significant", net, net_low, net_high, cost)

    # Point estimate only (e.g. a single backtest's Sharpe).
    bar = SHARPE_EDGE_BAR if spec.unit == "sharpe" else 0.0
    verdict = "edge" if net > spec.baseline + bar else "no_edge"
    return EdgeAssessment(verdict, "point_estimate", net, None, None, cost)


def pool_rate(pairs: list[tuple[float, int]]) -> tuple[float | None, int, float | None, float | None]:
    """Pool several rate estimates (value in [0,1], sample_count) into one
    sample-weighted rate with a Wilson interval on the combined counts.
    Returns (rate, total_n, low, high)."""
    total_n = sum(n for _, n in pairs if n > 0)
    if total_n <= 0:
        return None, 0, None, None
    successes = sum(round(v * n) for v, n in pairs if n > 0)
    rate = successes / total_n
    low, high = wilson_interval(successes, total_n)
    return rate, total_n, low, high
