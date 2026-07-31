"""End-to-end weld of the paper-order pipeline (live Phase 0).

Proves the chain the autonomous paper loop rides on is fully connected:

    trading_place_order tool  ->  trading.service.place_order
                              ->  alpaca-paper-trade profile (paper branch)
                              ->  connector place_order

with the real tool and real service routing exercised; only the Alpaca network
layer (``build_config`` / ``place_order``) is faked, since alpaca-py is an
optional dependency not installed in CI.

Also pins the deliberate design invariant that PAPER orders bypass the live
mandate gate (only live profiles route through ``execute_live_order``) — so any
future change that accidentally routes paper through the gate, or live around
it, fails here.
"""
from __future__ import annotations

import json

from src.trading.connectors.alpaca import sdk as alpaca_sdk
from src.tools.trading_connector_tool import TradingPlaceOrderTool


def _fake_alpaca(monkeypatch):
    calls: dict = {}

    def fake_build_config(profile_config=None, overrides=None):  # noqa: ANN001
        calls["build_config"] = (dict(profile_config or {}), dict(overrides or {}))
        return {"profile": "paper", "feed": "iex", "api_key": "", "secret_key": ""}

    def fake_place_order(config, **kw):  # noqa: ANN001
        calls["place_order"] = kw
        return {"status": "ok", "order_id": "sim-order-1", "symbol": kw["symbol"],
                "side": kw["side"], "is_paper": True, "order_status": "accepted"}

    monkeypatch.setattr(alpaca_sdk, "build_config", fake_build_config)
    monkeypatch.setattr(alpaca_sdk, "place_order", fake_place_order)
    return calls


def test_paper_order_routes_tool_through_service_to_connector(monkeypatch):
    calls = _fake_alpaca(monkeypatch)

    # The live gate must NEVER be reached on the paper path.
    import src.live.sdk_order_gate as gate
    monkeypatch.setattr(
        gate, "execute_live_order",
        lambda **_: (_ for _ in ()).throw(AssertionError("paper path invoked the live gate")),
    )

    out = json.loads(TradingPlaceOrderTool().execute(
        connection="alpaca-paper-trade", symbol="AAPL", side="buy", notional=100,
    ))

    # Tool/service pass the order through to the connector unchanged (the
    # connector does its own symbol normalization / validation).
    assert calls["place_order"]["symbol"] == "AAPL"
    assert calls["place_order"]["side"] == "buy"
    assert calls["place_order"]["notional"] == 100

    # Envelope is profile-tagged by the service and marks the paper sandbox.
    assert out["status"] == "ok"
    assert out["is_paper"] is True
    assert out["profile_id"] == "alpaca-paper-trade"
    assert out["environment"] == "paper"
    assert out["connector"] == "alpaca"


def test_place_order_tool_is_write_and_not_repeatable():
    # An order tool must never be silently re-issued by the agent loop.
    tool = TradingPlaceOrderTool()
    assert tool.is_readonly is False
    assert tool.repeatable is False
