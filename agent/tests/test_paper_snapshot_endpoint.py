"""The /live/paper-snapshot endpoint: shape + account-number redaction.

Read-only monitoring feed for the Paper account cockpit. Faked at the service
layer so it needs neither alpaca-py nor real keys.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import api_server
from src.trading import service


def test_paper_snapshot_combines_and_redacts(monkeypatch):
    monkeypatch.setattr(service, "get_account", lambda pid: {
        "status": "ok", "environment": "paper", "is_paper": True,
        "account": {"account_number": "PA-SECRET", "cash": "100000", "equity": "100000",
                    "buying_power": "400000", "status": "AccountStatus.ACTIVE"},
    })
    monkeypatch.setattr(service, "get_positions", lambda pid: {"status": "ok", "positions": [{"symbol": "AAPL", "qty": "1"}]})
    monkeypatch.setattr(service, "get_open_orders", lambda pid: {"status": "ok", "open_orders": []})

    body = TestClient(api_server.app).get("/live/paper-snapshot?profile_id=alpaca-paper-trade").json()

    assert body["connected"] is True
    assert body["is_paper"] is True
    assert body["account"]["cash"] == "100000"
    # account number must never reach the UI
    assert "account_number" not in body["account"]
    assert body["positions"] == [{"symbol": "AAPL", "qty": "1"}]
    assert body["open_orders"] == []


def test_paper_snapshot_reports_disconnected_on_connector_error(monkeypatch):
    # alpaca-py missing / bad keys → connector returns an error dict, not a raise;
    # the endpoint stays 200 and reports connected=false so the UI degrades cleanly.
    monkeypatch.setattr(service, "get_account", lambda pid: {"status": "error", "error": "Optional dependency missing"})
    monkeypatch.setattr(service, "get_positions", lambda pid: {"status": "error", "error": "x"})
    monkeypatch.setattr(service, "get_open_orders", lambda pid: {"status": "error", "error": "x"})

    resp = TestClient(api_server.app).get("/live/paper-snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["account_error"] == "Optional dependency missing"
