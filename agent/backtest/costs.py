"""Global transaction-cost model shared by every backtest path.

Single source of truth for commission, stamp duty, and per-side slippage,
resolved per market from the symbol suffix:

  - ``*.HK``               → Hong Kong
  - ``*.SS / *.SZ / *.BJ`` → China A-share
  - anything else           → US

All rates are basis points of traded notional. Defaults are deliberately
conservative retail assumptions:

  ==========  ==========  =========  ==========  ========
  market      commission  stamp buy  stamp sell  slippage
  ==========  ==========  =========  ==========  ========
  us          0.0         0.0        0.0         5.0
  hk          2.265       10.0       10.0        10.0
  cn          2.6         0.0        5.0         10.0
  ==========  ==========  =========  ==========  ========

  - HK commission bundles broker fee (万1.5) + SFC/FRC levies + CCASS.
  - HK stamp duty is 0.1% charged to each side (post-Nov-2023 rate).
  - CN commission bundles broker fee (万2.5) + transfer fee (万0.1);
    stamp duty is sell-only 0.05% (post-Aug-2023 rate).

Every rate can be overridden globally via environment variables, e.g.::

  VIBE_COST_HK_SLIPPAGE_BPS=20        # one market, one field
  VIBE_COST_SLIPPAGE_BPS=15           # all markets, one field

Market-specific variables win over the all-market form.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields

__all__ = [
    "MarketCosts",
    "market_of_code",
    "get_costs",
    "slipped_price",
    "trade_fee_rate",
    "trade_fee",
    "per_side_cost_bps",
]


@dataclass(frozen=True)
class MarketCosts:
    """Per-side transaction cost rates for one market, in basis points."""

    commission_bps: float  # broker commission + exchange levies, each side
    stamp_buy_bps: float   # stamp duty charged on buys
    stamp_sell_bps: float  # stamp duty charged on sells
    slippage_bps: float    # adverse price impact, each side


_DEFAULTS: dict[str, MarketCosts] = {
    "us": MarketCosts(commission_bps=0.0, stamp_buy_bps=0.0, stamp_sell_bps=0.0, slippage_bps=5.0),
    "hk": MarketCosts(commission_bps=2.265, stamp_buy_bps=10.0, stamp_sell_bps=10.0, slippage_bps=10.0),
    "cn": MarketCosts(commission_bps=2.6, stamp_buy_bps=0.0, stamp_sell_bps=5.0, slippage_bps=10.0),
}

_FIELD_ENV = {
    "commission_bps": "COMMISSION_BPS",
    "stamp_buy_bps": "STAMP_BUY_BPS",
    "stamp_sell_bps": "STAMP_SELL_BPS",
    "slippage_bps": "SLIPPAGE_BPS",
}


def market_of_code(code: str) -> str:
    """Map an internal symbol (``0700.HK`` / ``600519.SS`` / ``AAPL``) to a market key."""
    upper = (code or "").strip().upper()
    if upper.endswith(".HK"):
        return "hk"
    if upper.endswith((".SS", ".SZ", ".BJ")):
        return "cn"
    return "us"


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def get_costs(market: str) -> MarketCosts:
    """Resolve the cost table for *market*, applying env-var overrides.

    Not cached so tests and long-lived processes pick up env changes; four
    dict lookups per call is negligible next to a backtest bar loop.
    """
    key = market.lower()
    base = _DEFAULTS.get(key, _DEFAULTS["us"])
    values = {}
    for field in fields(MarketCosts):
        env_suffix = _FIELD_ENV[field.name]
        override = _env_float(f"VIBE_COST_{key.upper()}_{env_suffix}")
        if override is None:
            override = _env_float(f"VIBE_COST_{env_suffix}")
        values[field.name] = override if override is not None else getattr(base, field.name)
    return MarketCosts(**values)


def slipped_price(price: float, direction: int, market: str) -> float:
    """Execution price after adverse slippage: buys pay up, sells receive less.

    ``direction`` is +1 for buy/cover, -1 for sell/short.
    """
    rate = get_costs(market).slippage_bps / 1e4
    return price * (1 + direction * rate)


def trade_fee_rate(is_buy: bool, market: str) -> float:
    """Fee fraction of notional for one side (commission + applicable stamp)."""
    costs = get_costs(market)
    stamp = costs.stamp_buy_bps if is_buy else costs.stamp_sell_bps
    return (costs.commission_bps + stamp) / 1e4


def trade_fee(notional: float, is_buy: bool, market: str) -> float:
    """Absolute fee for trading *notional* on one side."""
    return abs(notional) * trade_fee_rate(is_buy, market)


def per_side_cost_bps(market: str) -> float:
    """Flat per-side cost for turnover-based simulators (|Δpos| × cost).

    Slippage + commission + average of buy/sell stamp, so a round trip
    charges exactly the true two-sided total.
    """
    costs = get_costs(market)
    return costs.slippage_bps + costs.commission_bps + (costs.stamp_buy_bps + costs.stamp_sell_bps) / 2.0
