"""US watchlist quotes: batched yfinance fallback and endpoint caching."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api_server


def _fake_batch_df(symbols: list[str]) -> pd.DataFrame:
    """Mimic yf.download(group_by='ticker') output for multiple symbols."""
    dates = pd.bdate_range("2025-06-02", periods=3)
    data = {}
    for i, sym in enumerate(symbols):
        base = 100.0 + i * 10
        data[(sym, "Close")] = [base, base + 1, base + 2]
    return pd.DataFrame(data, index=dates)


class TestUsQuotesYfinanceFallback:
    @pytest.fixture(autouse=True)
    def _no_alpaca(self, monkeypatch):
        monkeypatch.setattr(api_server, "_alpaca_us_quotes", lambda symbols: [])

    def test_batches_symbols_into_one_download(self, monkeypatch):
        calls = []

        def fake_download(symbols, **kwargs):
            calls.append(list(symbols))
            return _fake_batch_df(symbols)

        monkeypatch.setattr("yfinance.download", fake_download)

        out = api_server._fetch_us_watchlist_quotes(["AAPL", "MSFT"])

        assert calls == [["AAPL", "MSFT"]]
        aapl = next(q for q in out if q["code"] == "AAPL")
        assert aapl["price"] == 102.0
        assert aapl["prev_close"] == 101.0
        assert aapl["change_pct"] == pytest.approx(0.99, abs=0.01)

    def test_single_symbol_flat_frame(self, monkeypatch):
        dates = pd.bdate_range("2025-06-02", periods=2)
        flat = pd.DataFrame({"Close": [50.0, 51.0]}, index=dates)
        monkeypatch.setattr("yfinance.download", lambda *a, **kw: flat)

        out = api_server._fetch_us_watchlist_quotes(["AAPL"])

        assert out[0]["price"] == 51.0
        assert out[0]["prev_close"] == 50.0

    def test_single_symbol_multiindex_frame(self, monkeypatch):
        # yfinance(group_by="ticker") returns (sym, field) columns even for
        # one symbol — the shape that broke adding a single US stock.
        monkeypatch.setattr(
            "yfinance.download", lambda *a, **kw: _fake_batch_df(["AAPL"])
        )

        out = api_server._fetch_us_watchlist_quotes(["AAPL"])

        assert out[0]["price"] == 102.0
        assert out[0]["prev_close"] == 101.0
        assert "error" not in out[0]

    def test_failed_download_marks_symbols(self, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr("yfinance.download", boom)

        out = api_server._fetch_us_watchlist_quotes(["AAPL"])

        assert out[0]["error"] == "fetch_failed"
        assert out[0]["price"] == 0.0


class TestQuoteEndpointCache:
    def test_second_call_within_ttl_skips_upstream(self, monkeypatch):
        calls = []
        monkeypatch.setattr(api_server, "_WATCHLIST_QUOTE_CACHE", {})
        monkeypatch.setattr(
            api_server, "_fetch_us_watchlist_quotes",
            lambda codes: calls.append(codes) or [
                {"code": c, "name": c, "price": 1.0, "change_pct": 0.0, "prev_close": 1.0}
                for c in codes
            ],
        )
        client = TestClient(api_server.app)

        first = client.get("/watchlist/quote?codes=AAPL,MSFT&market=us")
        second = client.get("/watchlist/quote?codes=AAPL,MSFT&market=us")

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert len(calls) == 1

    def test_failed_result_is_not_cached(self, monkeypatch):
        calls = []
        monkeypatch.setattr(api_server, "_WATCHLIST_QUOTE_CACHE", {})
        monkeypatch.setattr(
            api_server, "_fetch_us_watchlist_quotes",
            lambda codes: calls.append(codes) or [
                {"code": c, "name": c, "price": 0.0, "change_pct": 0.0, "prev_close": 0.0, "error": "fetch_failed"}
                for c in codes
            ],
        )
        client = TestClient(api_server.app)

        client.get("/watchlist/quote?codes=AAPL&market=us")
        client.get("/watchlist/quote?codes=AAPL&market=us")

        assert len(calls) == 2
