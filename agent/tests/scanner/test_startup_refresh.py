from __future__ import annotations

import datetime as dt
import asyncio
import json
import threading

from src.scanner import startup_refresh


def test_runs_once_per_amsterdam_day(tmp_path, monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        startup_refresh,
        "run_daily",
        lambda universes: calls.append(tuple(universes)) or [],
    )
    marker = tmp_path / "daily-startup-refresh.json"

    assert startup_refresh.run_startup_refresh_once(
        state_path=marker, today=dt.date(2026, 7, 14),
    ) is True
    assert startup_refresh.run_startup_refresh_once(
        state_path=marker, today=dt.date(2026, 7, 14),
    ) is False
    assert startup_refresh.run_startup_refresh_once(
        state_path=marker, today=dt.date(2026, 7, 15),
    ) is True

    assert calls == [("hstech", "sp500"), ("hstech", "sp500")]
    assert json.loads(marker.read_text(encoding="utf-8"))["date"] == "2026-07-15"


def test_marks_attempt_before_swallowing_refresh_failure(tmp_path, monkeypatch, caplog):
    def fail(_universes):
        raise RuntimeError("feed unavailable")

    monkeypatch.setattr(startup_refresh, "run_daily", fail)
    marker = tmp_path / "daily-startup-refresh.json"

    assert startup_refresh.run_startup_refresh_once(
        state_path=marker, today=dt.date(2026, 7, 14),
    ) is True
    assert startup_refresh.run_startup_refresh_once(
        state_path=marker, today=dt.date(2026, 7, 14),
    ) is False

    assert json.loads(marker.read_text(encoding="utf-8"))["date"] == "2026-07-14"
    assert "feed unavailable" in caplog.text


def test_schedule_returns_while_refresh_runs_in_background(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def block():
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(startup_refresh, "run_startup_refresh_once", block)

    async def exercise():
        task = startup_refresh.schedule_startup_refresh()
        assert await asyncio.to_thread(started.wait, 1)
        assert task.done() is False
        release.set()
        await task

    asyncio.run(exercise())
