# Startup And Health Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local startup deterministic and expose actionable frontend/backend health failures.

**Architecture:** `scripts/dev` owns process and proxy diagnostics. A small React hook polls the proxied `/health` contract, and the existing banner renders API failures independently from chat SSE state.

**Tech Stack:** Bash, pytest subprocess tests, React, TypeScript, Vitest, Vite, FastAPI.

## Global Constraints

- Keep default ports `5899/8899` fixed.
- Do not change investment or market-data behavior.
- Add no runtime dependencies.
- Never expose returned HTML in an API error.

---

### Task 1: Developer diagnostics

**Files:** `scripts/dev`, `agent/tests/test_dev_script.py`

- [ ] Add failing subprocess tests for unknown `doctor`, stopped services, healthy proxy and stale PID cleanup.
- [ ] Run the focused pytest file and confirm the expected failures.
- [ ] Implement stale PID cleanup, occupied-port diagnostics, JSON health validation, proxy validation and `doctor`.
- [ ] Run focused pytest and `bash -n scripts/dev`.
- [ ] Commit Task 1.

### Task 2: Frontend health contract

**Files:** `frontend/vite.config.ts`, `frontend/src/hooks/useApiHealth.ts`, `frontend/src/hooks/__tests__/useApiHealth.test.ts`

- [ ] Add failing hook tests for healthy JSON, HTML, network failure, interval and manual retry.
- [ ] Run the focused Vitest file and confirm it fails because the hook is absent.
- [ ] Proxy `/health` and implement `useApiHealth(): { status, retry }` with strict validation and cleanup.
- [ ] Run focused tests and commit Task 2.

### Task 3: Connection UX and sanitized errors

**Files:** `frontend/src/components/layout/ConnectionBanner.tsx`, `frontend/src/components/layout/Layout.tsx`, banner tests, `frontend/src/lib/api.ts`, API error tests.

- [ ] Add failing tests for API priority, retry, healthy SSE behavior and sanitized HTML errors.
- [ ] Implement API-aware banner, Layout wiring and HTML-safe error text.
- [ ] Run focused and full frontend tests plus production build.
- [ ] Commit Task 3.

### Task 4: End-to-end verification

**Files:** `CHANGELOG.md`

- [ ] Restart services and require `scripts/dev doctor` to pass.
- [ ] Verify direct and proxied health JSON.
- [ ] Stop/restart backend and verify the browser banner appears then clears.
- [ ] Run backend focused tests, frontend tests, build and `git diff --check`.
- [ ] Update changelog and commit Task 4.
