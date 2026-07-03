# Overview Price Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render overview stock charts immediately from a persistent browser cache and refresh stale data in the background.

**Architecture:** Add a small typed local-storage cache with explicit keys and freshness metadata. `StockChartCard` reads history and quote caches independently, skips fresh requests, and uses stale values while revalidating expired entries.

**Tech Stack:** React, TypeScript, Vitest, browser localStorage.

## Global Constraints

- Historical price TTL is 24 hours.
- Quote TTL is 60 seconds.
- History keys include market, symbol, and period.
- Quote keys include market and symbol.
- Expired values remain displayable while a background request refreshes them.
- Storage failures must fall back to normal network behavior.

---

### Task 1: Persistent cache utility

**Files:**
- Create: `frontend/src/lib/overview-price-cache.ts`
- Create: `frontend/src/lib/__tests__/overview-price-cache.test.ts`

- [ ] Write failing tests for key isolation, fresh reads, stale reads, and malformed storage.
- [ ] Run the focused test and verify failure because the module is absent.
- [ ] Implement `historyCacheKey`, `quoteCacheKey`, `readOverviewCache`, and `writeOverviewCache`.
- [ ] Re-run the focused test and verify success.

### Task 2: Stock chart stale-while-revalidate flow

**Files:**
- Modify: `frontend/src/pages/Overview.tsx`
- Modify: `frontend/src/pages/__tests__/OverviewIndexCards.test.tsx`

- [ ] Read cached history and quote before issuing requests.
- [ ] Skip history or quote requests independently while each cache entry is fresh.
- [ ] Keep stale history visible without showing an empty loading chart while refreshing.
- [ ] Save successful network responses into their corresponding cache entries.
- [ ] Run overview tests, the frontend build, and `git diff --check`.

### Task 3: Local development loader cache

**Files:**
- Modify: `scripts/dev`

- [ ] Default `VIBE_TRADING_DATA_CACHE` to `1` for the local development backend while preserving an explicit caller override.
- [ ] Verify shell syntax with `bash -n scripts/dev`.
