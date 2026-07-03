# Robust Winner Auto Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically create and display a normal paper-trading run after multi-period optimization selects its most robust strategy.

**Architecture:** Add a small request builder that converts the robust winner plus current form state into the existing `PaperTradingCreate` contract. The page keeps the robustness matrix, creates the winner run, and hands its ID to the existing polling path.

**Tech Stack:** React, TypeScript, Vitest, existing paper-trading API.

## Global Constraints

- Reuse the current holdings, dates, cash values, DCA frequency, grid count, and strategy defaults.
- Keep the robustness result visible while the winner backtest runs.
- Do not create a run when `best_strategy` is absent.
- Reuse existing run polling and result rendering.

---

### Task 1: Winner request contract

**Files:**
- Create: `frontend/src/lib/paper-trading-robust.ts`
- Create: `frontend/src/lib/__tests__/paper-trading-robust.test.ts`

**Interfaces:**
- Produces: `buildRobustWinnerRunRequest(input): PaperTradingCreate`.

- [ ] Write a failing test asserting the winner name, winner params, holdings, dates, and cash are preserved.
- [ ] Run `npm --prefix frontend run test:run -- src/lib/__tests__/paper-trading-robust.test.ts` and confirm failure.
- [ ] Implement the minimal request builder and reject a missing winner with `No robust winner available`.
- [ ] Re-run the focused test and confirm it passes.

### Task 2: Automatic execution

**Files:**
- Modify: `frontend/src/pages/PaperTrading.tsx`

**Interfaces:**
- Consumes: `buildRobustWinnerRunRequest` and existing `api.createPaperTradingRun` / `pollRun`.

- [ ] After `setRobustResult(result)`, build the winner request from current form state.
- [ ] Set the strategy selector to the winner, create the run, set it active, and call `pollRun(run.run_id)`.
- [ ] Keep `robustLoading` true until run creation succeeds or fails; preserve `robustResult` on failure.
- [ ] Run the focused test, `npm --prefix frontend run build`, and `git diff --check`.
