"""The robust-selection disk cache is shared by the API and the auto-executor.

Before this was extracted the paper executor recomputed the annual selection on
every tick: slow, and a dual-source risk (the executor could pick a different
strategy than the one the forecast UI displays).
"""
from __future__ import annotations

import api_server
from src.paper_trading import selection_cache as sc


def test_api_and_executor_agree_on_the_cache_key():
    # api_server delegates to the shared key builder, so a selection cached by
    # one surface is found by the other.
    key = sc.selection_cache_key("us", "AAPL")
    assert key.startswith("forecast-robust-selection:us:AAPL:")


def test_roundtrip_and_ttl_expiry(tmp_path, monkeypatch):
    sc.write_cache("k", {"selected_strategy": "donchian_breakout"}, tmp_path)
    assert sc.read_cache("k", 3600, tmp_path) == {"selected_strategy": "donchian_breakout"}
    # A zero TTL means anything on disk is already stale.
    assert sc.read_cache("k", 0, tmp_path) is None
    assert sc.read_cache("missing", 3600, tmp_path) is None


def test_api_server_helpers_read_what_the_shared_module_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "_BEST_STRATEGY_DISK_CACHE_DIR", tmp_path)
    key = sc.selection_cache_key("us", "NVDA")
    sc.write_cache(key, {"selected_strategy": "buy_and_hold"}, tmp_path)

    got = api_server._read_best_strategy_disk_cache(key, sc.SELECTION_TTL_SECONDS)
    assert got == {"selected_strategy": "buy_and_hold"}


def test_executor_writes_are_visible_to_api_server(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "_BEST_STRATEGY_DISK_CACHE_DIR", tmp_path)
    key = sc.selection_cache_key("us", "MSFT")
    api_server._write_best_strategy_disk_cache(key, {"selected_strategy": "ma200_timing"})

    assert sc.read_cache(key, sc.SELECTION_TTL_SECONDS, tmp_path) == {"selected_strategy": "ma200_timing"}
