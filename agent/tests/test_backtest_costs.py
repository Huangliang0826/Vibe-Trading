"""Tests for the shared transaction-cost model (backtest.costs)."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.costs import (
    get_costs,
    market_of_code,
    per_side_cost_bps,
    slipped_price,
    trade_fee,
    trade_fee_rate,
)


class TestMarketOfCode:
    def test_hk(self) -> None:
        assert market_of_code("0700.HK") == "hk"

    def test_cn_shanghai(self) -> None:
        assert market_of_code("600519.SS") == "cn"

    def test_cn_shenzhen(self) -> None:
        assert market_of_code("300750.SZ") == "cn"

    def test_cn_beijing(self) -> None:
        assert market_of_code("830799.BJ") == "cn"

    def test_us_suffixed(self) -> None:
        assert market_of_code("AAPL.US") == "us"

    def test_us_bare(self) -> None:
        assert market_of_code("AAPL") == "us"

    def test_lowercase(self) -> None:
        assert market_of_code("0700.hk") == "hk"

    def test_empty(self) -> None:
        assert market_of_code("") == "us"


class TestDefaults:
    def test_us_no_commission_no_stamp(self) -> None:
        costs = get_costs("us")
        assert costs.commission_bps == 0.0
        assert costs.stamp_buy_bps == 0.0
        assert costs.stamp_sell_bps == 0.0
        assert costs.slippage_bps > 0

    def test_hk_stamp_bilateral(self) -> None:
        costs = get_costs("hk")
        assert costs.stamp_buy_bps == costs.stamp_sell_bps == 10.0
        assert costs.commission_bps > 0

    def test_cn_stamp_sell_only(self) -> None:
        costs = get_costs("cn")
        assert costs.stamp_buy_bps == 0.0
        assert costs.stamp_sell_bps == 5.0

    def test_unknown_market_falls_back_to_us(self) -> None:
        assert get_costs("xx") == get_costs("us")


class TestEnvOverrides:
    def test_market_specific(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_COST_HK_SLIPPAGE_BPS", "20")
        assert get_costs("hk").slippage_bps == 20.0
        assert get_costs("us").slippage_bps == 5.0  # untouched

    def test_all_market(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_COST_SLIPPAGE_BPS", "15")
        assert get_costs("us").slippage_bps == 15.0
        assert get_costs("hk").slippage_bps == 15.0

    def test_specific_wins_over_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_COST_SLIPPAGE_BPS", "15")
        monkeypatch.setenv("VIBE_COST_HK_SLIPPAGE_BPS", "25")
        assert get_costs("hk").slippage_bps == 25.0
        assert get_costs("us").slippage_bps == 15.0

    def test_invalid_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_COST_US_SLIPPAGE_BPS", "banana")
        assert get_costs("us").slippage_bps == 5.0

    def test_negative_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIBE_COST_US_SLIPPAGE_BPS", "-3")
        assert get_costs("us").slippage_bps == 5.0


class TestSlippedPrice:
    def test_buy_pays_up(self) -> None:
        assert slipped_price(100.0, 1, "us") == pytest.approx(100.05)

    def test_sell_receives_less(self) -> None:
        assert slipped_price(100.0, -1, "us") == pytest.approx(99.95)

    def test_hk_wider(self) -> None:
        assert slipped_price(100.0, 1, "hk") == pytest.approx(100.10)


class TestFees:
    def test_hk_buy_fee(self) -> None:
        # commission 2.265bp + stamp 10bp = 12.265bp
        assert trade_fee(100_000.0, True, "hk") == pytest.approx(122.65)

    def test_cn_sell_includes_stamp(self) -> None:
        # commission 2.6bp + sell stamp 5bp = 7.6bp
        assert trade_fee(100_000.0, False, "cn") == pytest.approx(76.0)

    def test_cn_buy_excludes_stamp(self) -> None:
        assert trade_fee(100_000.0, True, "cn") == pytest.approx(26.0)

    def test_us_buy_free_except_slippage(self) -> None:
        assert trade_fee(100_000.0, True, "us") == 0.0

    def test_rate_matches_fee(self) -> None:
        assert trade_fee_rate(True, "hk") == pytest.approx(122.65 / 100_000)


class TestPerSideCostBps:
    def test_round_trip_totals_match(self) -> None:
        """2 × per-side must equal the true two-sided total."""
        for market in ("us", "hk", "cn"):
            costs = get_costs(market)
            true_round_trip = (
                2 * costs.slippage_bps
                + 2 * costs.commission_bps
                + costs.stamp_buy_bps
                + costs.stamp_sell_bps
            )
            assert 2 * per_side_cost_bps(market) == pytest.approx(true_round_trip)

    def test_hk_realistic_magnitude(self) -> None:
        # ~22bp per side for HK — far from the old flat 5bp
        assert per_side_cost_bps("hk") == pytest.approx(22.265)


class TestEngineIntegration:
    """Per-symbol cost resolution inside GlobalEquityEngine."""

    def _run(self, code: str, market: str):
        from backtest.engines.global_equity import GlobalEquityEngine

        dates = pd.bdate_range("2025-01-02", periods=3)
        bars = pd.DataFrame(
            {"open": [100.0] * 3, "close": [100.0] * 3}, index=dates,
        )
        close_df = bars[["close"]].rename(columns={"close": code})
        target_pos = pd.DataFrame({code: [1.0] * 3}, index=dates)
        engine = GlobalEquityEngine({"initial_cash": 1_000_000}, market=market)
        engine._execute_bars(dates, {code: bars}, close_df, target_pos, [code])
        return engine

    def test_hk_leg_pays_stamp_in_mixed_us_engine(self) -> None:
        """The old behaviour charged zero commission on HK legs of mixed runs."""
        engine = self._run("0700.HK", market="us")
        assert engine.trades, "expected a forced end-of-backtest trade"
        assert engine.trades[-1].commission > 0

    def test_a_share_pays_sell_stamp(self) -> None:
        engine = self._run("600519.SS", market="us")
        trade = engine.trades[-1]
        # Buy: commission only. Sell: commission + stamp — total > 2× buy leg.
        notional_bps = trade.commission / (trade.size * 100.0) * 1e4
        assert notional_bps == pytest.approx(2.6 + 2.6 + 5.0, rel=0.05)

    def test_us_leg_still_free(self) -> None:
        engine = self._run("AAPL.US", market="us")
        assert engine.trades[-1].commission == 0.0


class TestSimulatorIntegration:
    """Inline simulators (DCA) charge costs and reduce final equity."""

    def _dca_equity(self, code: str, market: str) -> tuple[float, float]:
        from src.paper_trading.executor import _run_dca
        from src.paper_trading.models import PaperHolding

        dates = pd.bdate_range("2024-01-01", periods=260)
        bars = pd.DataFrame(
            {"open": [100.0] * 260, "close": [100.0] * 260}, index=dates,
        )
        holding = PaperHolding(symbol=code, market=market, allocation_pct=100.0)
        from src.paper_trading.strategies import _to_code

        internal = _to_code(holding)
        equity, trades = _run_dca(
            100_000.0, [holding], {internal: bars}, {"frequency": "monthly"},
        )
        total_commission = sum(t.commission for t in trades)
        return float(equity.iloc[-1]), total_commission

    def test_hk_dca_pays_costs(self) -> None:
        final_equity, commission = self._dca_equity("0700", "hk")
        # Flat price: every dollar lost is slippage + fees.
        assert final_equity < 100_000.0
        assert commission > 0

    def test_us_dca_only_slippage(self) -> None:
        final_equity, commission = self._dca_equity("AAPL", "us")
        assert final_equity < 100_000.0  # slippage only, but still < start
        assert commission == 0.0
