# Daily Startup Preload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing daily scanner/news refresh once in the background on the first backend startup of each Amsterdam calendar day.

**Architecture:** Add one small helper that owns a date marker and calls `scanner.schedule.run_daily()`. The FastAPI startup hook schedules that synchronous helper with `asyncio.to_thread()` so HTTP startup remains responsive.

**Tech Stack:** Python 3.13, FastAPI, pytest, pathlib, zoneinfo.

## Global Constraints

- Reuse `run_daily()`; do not duplicate scanner or news logic.
- Use one daily marker rather than a new scheduler or per-component state machine.
- Do not generate AI news summaries during startup.
- Keep existing page-level and manual refresh behavior unchanged.

---

### Task 1: Daily startup refresh helper and integration

**Files:**
- Create: `agent/src/scanner/startup_refresh.py`
- Create: `agent/tests/scanner/test_startup_refresh.py`
- Modify: `agent/api_server.py`

**Interfaces:**
- Produces: `run_startup_refresh_once(*, state_path: Path | None = None, today: date | None = None) -> bool`; returns `True` when it starts the daily work and `False` when today's marker already exists.
- Consumes: `scanner.schedule.DEFAULT_UNIVERSES` and `scanner.schedule.run_daily()`.

- [ ] **Step 1: Write failing unit tests**

Cover first call, same-day skip, next-day rerun, and marker persistence while `run_daily()` raises.

- [ ] **Step 2: Verify the tests fail**

Run: `cd agent && ../.venv/bin/pytest tests/scanner/test_startup_refresh.py -q`

Expected: FAIL because `src.scanner.startup_refresh` does not exist.

- [ ] **Step 3: Implement the minimal helper**

Use `ZoneInfo("Europe/Amsterdam")`, store one JSON marker in the runtime data directory, write the marker before calling `run_daily(DEFAULT_UNIVERSES)`, log errors, and return without re-raising them.

- [ ] **Step 4: Integrate it into FastAPI startup**

Keep a module-level task reference and call `asyncio.create_task(asyncio.to_thread(run_startup_refresh_once))` from the existing startup hook. Do not await the data refresh.

- [ ] **Step 5: Verify targeted and full suites**

Run:

```bash
cd agent && ../.venv/bin/pytest tests/scanner/test_startup_refresh.py tests/scanner/test_schedule.py -q
cd agent && ../.venv/bin/pytest -q
cd frontend && npm test -- --run && npm run build
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add agent/src/scanner/startup_refresh.py agent/tests/scanner/test_startup_refresh.py agent/api_server.py docs/superpowers
git commit -m "feat: preload daily market content on startup"
```
