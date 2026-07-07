"""A-share capital-flow: code normalization, parsing, and bundle degradation."""
from __future__ import annotations

from src import market_data_astock as m


class TestNormalizeCode:
    def test_plain_six_digits(self):
        assert m.normalize_a_code("600519") == "600519"

    def test_strips_suffix_and_prefix(self):
        assert m.normalize_a_code("600519.SH") == "600519"
        assert m.normalize_a_code("sh600519") == "600519"

    def test_rejects_non_a_share(self):
        assert m.normalize_a_code("AAPL") is None
        assert m.normalize_a_code("00700") is None  # 5-digit HK -> not A-share
        assert m.normalize_a_code("0700") is None   # 4-digit -> not A-share


class TestParsers:
    def test_margin_maps_fields(self, monkeypatch):
        monkeypatch.setattr(m, "_datacenter", lambda *a, **k: [
            {"DATE": "2026-07-06T00:00:00", "RZYE": 1.0e8, "RZMRE": 2.0e7,
             "RQYE": 3.0e6, "RZRQYE": 1.03e8},
        ])
        rows = m.margin_trading("600519")
        assert rows[0] == {"date": "2026-07-06", "rzye": 1.0e8, "rzmre": 2.0e7,
                           "rqye": 3.0e6, "rzrqye": 1.03e8}

    def test_block_trade_computes_premium(self, monkeypatch):
        monkeypatch.setattr(m, "_datacenter", lambda *a, **k: [
            {"TRADE_DATE": "2026-06-26", "DEAL_PRICE": 322, "CLOSE_PRICE": 381,
             "DEAL_AMT": 2.03e6, "BUYER_NAME": "机构", "SELLER_NAME": "营业部"},
        ])
        rows = m.block_trade("600519")
        assert rows[0]["premium_pct"] == round((322 / 381 - 1) * 100, 2)

    def test_block_trade_zero_close_no_div_by_zero(self, monkeypatch):
        monkeypatch.setattr(m, "_datacenter", lambda *a, **k: [
            {"TRADE_DATE": "2026-06-26", "DEAL_PRICE": 10, "CLOSE_PRICE": 0},
        ])
        assert m.block_trade("600519")[0]["premium_pct"] == 0


class TestBundleDegradation:
    def test_non_a_share_short_circuits(self):
        assert m.fetch_capital_flow("AAPL") == {"code": "AAPL", "error": "not_a_share"}

    def test_failing_section_becomes_empty_not_crash(self, monkeypatch):
        def boom(_code):
            raise RuntimeError("throttled")

        monkeypatch.setattr(m, "margin_trading", boom)
        monkeypatch.setattr(m, "holder_num_change", lambda c: [{"date": "x"}])
        monkeypatch.setattr(m, "block_trade", boom)
        monkeypatch.setattr(m, "dividend_history", lambda c: [])
        monkeypatch.setattr(m, "stock_fund_flow_120d", boom)

        out = m.fetch_capital_flow("600519")

        assert out["code"] == "600519"
        assert out["margin"] == []          # failed -> empty
        assert out["holders"] == [{"date": "x"}]
        assert out["fund_flow"] == []
        assert out["fund_flow_20d_main_net"] == 0
