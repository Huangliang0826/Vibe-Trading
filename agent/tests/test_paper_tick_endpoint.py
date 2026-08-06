"""The /live/paper-tick trigger endpoints (live Phase 2b).

The tick itself is slow, so the POST returns immediately and the UI polls GET.
We stub the background scheduling so the contract (running / already_running /
GET reflects state) is deterministic.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import api_server


def _no_bg(monkeypatch):
    # Don't actually schedule the slow tick; just discard the coroutine.
    def fake_create_task(coro):
        coro.close()
        return None
    monkeypatch.setattr(api_server.asyncio, "create_task", fake_create_task)


def test_post_starts_running_and_get_reflects(monkeypatch):
    _no_bg(monkeypatch)
    api_server._PAPER_TICK_STATE.update(status="idle", dry_run=None, result=None, error=None)
    client = TestClient(api_server.app)
    try:
        r1 = client.post("/live/paper-tick?dry_run=true").json()
        assert r1["status"] == "running"
        assert r1["dry_run"] is True
        assert r1["already_running"] is False

        # A second trigger while running does not start another run.
        r2 = client.post("/live/paper-tick?dry_run=true").json()
        assert r2["already_running"] is True

        assert client.get("/live/paper-tick").json()["status"] == "running"
    finally:
        api_server._PAPER_TICK_STATE.update(status="idle", dry_run=None, result=None, error=None)
