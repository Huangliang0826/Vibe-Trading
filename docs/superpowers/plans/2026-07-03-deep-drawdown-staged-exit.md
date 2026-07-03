# Deep Drawdown Staged Exit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change `deep_drawdown_recovery` to hold a permanent 25% core position while the remaining 75% uses a rolling three-year high, ten monthly entry tranches, and five monthly exits after price reaches 140% of tactical weighted average cost.

**Architecture:** Keep the strategy in the shared paper-trading executor so single runs and robust optimization use identical behavior. Store each symbol's scheduled entry and exit dates in isolated per-symbol state, and make every decision from the previous close before executing at the next open.

**Tech Stack:** Python, pandas, pytest, React, TypeScript, Vitest.

## Global Constraints

- Use the highest known close from the previous three calendar years; use available history when shorter.
- Buy a permanent 25% core position on the first trading day and never sell it.
- Apply all drawdown entries and staged exits only to the remaining 75% tactical budget.
- Trigger entry at a 40% drawdown and split the budget into 10 monthly tranches.
- Trigger exit at 140% of weighted average cost and sell in 5 monthly tranches.
- Once an exit schedule starts, price declines do not cancel it.
- Do not use same-day close information to trade at that day's open.

---

### Task 1: Strategy execution behavior

**Files:**
- Modify: `agent/tests/test_paper_trading_lookahead.py`
- Modify: `agent/src/paper_trading/executor.py`

**Interfaces:**
- Consumes: `evaluate_strategy(..., strategy_name="deep_drawdown_recovery", params, initial_cash)`.
- Produces: an equity series and `TradeRecord` rows containing one permanent core purchase plus tactical entries spanning 10 months and tactical exits spanning 5 months.

- [ ] **Step 1: Replace the old six-tranche test with failing tests**

Create deterministic OHLCV frames that assert: 25% buys on the first trading day and remains open through the backtest; the remaining 75% forms ten equal monthly entry tranches; the core cost does not affect the 140% tactical trigger; five tactical exits occur at the next open and monthly thereafter; falling prices do not cancel scheduled exits.

- [ ] **Step 2: Verify the tests fail**

Run: `uv run pytest agent/tests/test_paper_trading_lookahead.py -q`

Expected: failures showing six entries and a single 130% exit under the old implementation.

- [ ] **Step 3: Implement the state machine**

In `_run_deep_drawdown_recovery`, use defaults:

```python
drawdown_threshold = 0.40
take_profit_pct = 0.40
tranche_count = 10
exit_tranche_count = 5
lookback_years = 3
core_position_pct = 0.25
```

Buy the core position separately on the first trading day. Compute the rolling high from closes strictly before the current execution day and no earlier than `ts - pd.DateOffset(years=3)`. On trigger, schedule ten tactical buys from the 75% sleeve. On take-profit trigger, freeze only tactical shares, sell one fifth immediately, and schedule four further tactical sales on subsequent monthly first trading days. Never pass core shares to the staged-sale function.

- [ ] **Step 4: Verify strategy tests pass**

Run: `uv run pytest agent/tests/test_paper_trading_lookahead.py agent/tests/test_paper_trading_robust.py -q`

Expected: all tests pass.

### Task 2: Shared defaults and product copy

**Files:**
- Modify: `agent/src/paper_trading/hstech_best.py`
- Modify: `agent/tests/test_hstech_best_strategy.py`
- Modify: `frontend/src/pages/PaperTrading.tsx`

**Interfaces:**
- Produces backend and frontend defaults `{core_position_pct: 0.25, drawdown_threshold: 0.4, take_profit_pct: 0.4, tranches: 10, exit_tranches: 5, lookback_years: 3}`.

- [ ] **Step 1: Update the backend default contract test first**

Change `test_strategy_params_exposes_catalog_defaults` to assert the exact new parameter dictionary and run it to observe failure.

- [ ] **Step 2: Update shared defaults and labels**

Update `strategy_params`, the backend strategy principle, the simulated-trading strategy description, and `strategyParamsFor` to describe and send the exact new rules.

- [ ] **Step 3: Run verification**

Run:

```bash
uv run pytest agent/tests/test_hstech_best_strategy.py agent/tests/test_paper_trading_lookahead.py agent/tests/test_paper_trading_robust.py -q
npm --prefix frontend run build
git diff --check
```

Expected: all selected tests and the frontend build pass with no whitespace errors.
