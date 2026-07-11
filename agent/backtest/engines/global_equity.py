"""Global equity (US / HK / A-share) backtest engine.

Market rules:
  US:
    - T+0, long/short allowed
    - Zero commission (retail brokers)
    - Fractional shares supported (round to 0.01)
    - Low slippage (high liquidity)
  HK:
    - T+0, long/short allowed
    - Stamp tax 0.1% bilateral + levies
    - Lot-size rounding (simplified to 100 shares)
    - Higher slippage than US
  A-share (``.SS/.SZ/.BJ`` symbols):
    - Commission + transfer fee, stamp tax sell-only

Commission and slippage resolve **per symbol** from the shared cost model
(``backtest.costs``): a mixed portfolio run under ``market="us"`` still
charges HK stamp tax on its ``.HK`` legs and A-share stamp on ``.SS/.SZ``
legs. The ``market`` parameter remains the engine-level default for calls
outside a bar loop and controls lot rounding.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from backtest.costs import get_costs, market_of_code
from backtest.engines.base import BaseEngine


class GlobalEquityEngine(BaseEngine):
    """US / HK / A-share equity engine; *market* sets default rules.

    Config keys (legacy overrides, fractions not bps):
      - slippage_us: e.g. 0.0005
      - slippage_hk: e.g. 0.001
      - hk_stamp_tax: default 0.001 (0.1% bilateral)
      - hk_commission: default 0.00015 (万1.5)
      - hk_levy: default 0.0000565 (SFC + FRC)
      - hk_settlement: default 0.00002 (CCASS)
    """

    def __init__(self, config: dict, market: str = "us"):
        config = {**config, "leverage": config.get("leverage", 1.0)}
        super().__init__(config)
        self.market = market

        # Legacy component attributes, kept for compat and config overrides.
        self.slippage_us: float = config.get("slippage_us", get_costs("us").slippage_bps / 1e4)
        self.slippage_hk: float = config.get("slippage_hk", get_costs("hk").slippage_bps / 1e4)
        self.hk_stamp_tax: float = config.get("hk_stamp_tax", 0.001)
        self.hk_commission: float = config.get("hk_commission", 0.00015)
        self.hk_levy: float = config.get("hk_levy", 0.0000565)
        self.hk_settlement: float = config.get("hk_settlement", 0.00002)

        # Per-market cost tables from the global model, with legacy config
        # keys layered on top so existing callers keep their exact rates.
        hk_commission_bps = (self.hk_commission + self.hk_levy + self.hk_settlement) * 1e4
        hk_stamp_bps = self.hk_stamp_tax * 1e4
        self._costs = {
            "us": replace(get_costs("us"), slippage_bps=self.slippage_us * 1e4),
            "hk": replace(
                get_costs("hk"),
                slippage_bps=self.slippage_hk * 1e4,
                commission_bps=hk_commission_bps,
                stamp_buy_bps=hk_stamp_bps,
                stamp_sell_bps=hk_stamp_bps,
            ),
            "cn": get_costs("cn"),
        }

    def _effective_market(self) -> str:
        """Market for the symbol being traded, falling back to engine default."""
        if self._active_symbol:
            return market_of_code(self._active_symbol)
        return self.market if self.market in self._costs else "us"

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """US/HK: T+0, both directions allowed."""
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """US: fractional shares (0.01). HK: 100-share lots."""
        if self.market == "hk":
            return max(int(raw_size / 100) * 100, 0)
        return round(max(raw_size, 0.0), 2)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """Commission + stamp duty for the active symbol's market.

        Buy/sell is derived from position direction and open/close: opening a
        long or closing a short buys; the other two sell. Short-borrow fees
        (US Reg-T margin, HK SBL) are still out of scope.
        """
        costs = self._costs[self._effective_market()]
        is_buy = (direction == 1) == is_open
        stamp = costs.stamp_buy_bps if is_buy else costs.stamp_sell_bps
        return size * price * (costs.commission_bps + stamp) / 1e4

    def apply_slippage(self, price: float, direction: int) -> float:
        """Adverse slippage at the active symbol's market rate."""
        rate = self._costs[self._effective_market()].slippage_bps / 1e4
        return price * (1 + direction * rate)
