# Task 4 Report: Market Inputs and No-Lookahead Strategy Context

## Status

- Implemented deterministic market and strategy context loaders in:
  - [market_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/market_context.py)
  - [strategy_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/strategy_context.py)
- Kept the shared strategy ranking order in sync with a minimal public wrapper in:
  - [hstech_best.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/paper_trading/hstech_best.py)
- Extended the strict contract for `StrategyContext` with `data_as_of` in:
  - [models.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/models.py)
- Added Task 4 tests in:
  - [test_strategy_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_strategy_context.py)
  - [test_market_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_market_context.py)
- Updated model coverage in:
  - [test_models.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_models.py)

## Implementation

- `evaluate_strategy_context()` now loads daily OHLCV up to `as_of`, enforces a 504-row minimum, uses the final 252 rows as OOS, selects the winner on training metrics only, and reports the selected strategy's OOS return / Sharpe / max drawdown plus `data_as_of`.
- `evaluate_frame()` is a pure helper for offline tests; it trims to `as_of` before any calculation, so mutating future rows cannot change the result.
- Current strategy action is derived from the final target-weight transition only:
  - `0 -> >0` => `entry`
  - `higher positive` => `add`
  - `>0 -> 0` => `exit`
  - unchanged positive => `hold`
  - unchanged zero => `wait`
- The action path does not inspect engine `end_of_backtest` liquidation trades.
- DCA-family selection uses the repo's existing `_run_dca()` execution path for training/OOS metrics, while the action still comes from deterministic target-weight changes.
- `load_market_context()` now computes exact trend/risk inputs from prices up to `as_of` only:
  - `sma50`, `sma200`
  - `momentum63`
  - `annual_vol`, `downside_vol`, `max_drawdown`
  - `volume_ratio`
- Trend and risk scores follow the exact formulas from the plan, including `volume_confirmation`.
- HK valuation uses five-year PE history first and falls back to PB only when PE has fewer than 30 positive points. US valuation remains `None`.

## RED / GREEN Evidence

### RED

1. Wrote the Task 4 tests first:
   - [test_strategy_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_strategy_context.py)
   - [test_market_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_market_context.py)
2. Ran:
   - `uv run pytest agent/tests/opportunity_center/test_strategy_context.py agent/tests/opportunity_center/test_market_context.py -v`
3. Observed expected missing-implementation failures:
   - `ModuleNotFoundError: No module named 'src.opportunity_center.strategy_context'`
   - `ModuleNotFoundError: No module named 'src.opportunity_center.market_context'`

### GREEN

1. Implemented the new Task 4 modules and minimal shared helper/model updates.
2. Re-ran the Task 4 suites:
   - `uv run pytest agent/tests/opportunity_center/test_strategy_context.py agent/tests/opportunity_center/test_market_context.py -v`
   - Result: `13 passed in 5.19s`
3. Ran the exact focused regression command from the brief:
   - `uv run pytest agent/tests/opportunity_center/test_strategy_context.py agent/tests/opportunity_center/test_market_context.py agent/tests/test_paper_trading_lookahead.py -v`
   - Result: `19 passed in 5.07s`
4. Ran nearby regression coverage for touched contracts/helpers:
   - `uv run pytest agent/tests/opportunity_center/test_strategy_context.py agent/tests/opportunity_center/test_market_context.py agent/tests/test_paper_trading_lookahead.py agent/tests/opportunity_center/test_models.py agent/tests/test_hstech_best_strategy.py -v`
   - Result: `30 passed in 5.13s`
5. Patch hygiene:
   - `git diff --check`
   - Result: clean

## Self-Review

- I manually reviewed the Task 4 diff against the brief after the final green runs.
- I also attempted to dispatch a separate review agent, but no review-capable subagent type was available in this session, so the review remained manual.
- No blocking issues found in the final diff.
- One mid-review correction was required: the first implementation ranked DCA-family strategies through the generic weight engine, which could drift from existing repo behavior. I corrected that so `dca` / `smart_dca` metrics now reuse `_run_dca()` for selection and OOS evaluation.

## Concerns

- HK valuation history depends on the existing `api_server._fetch_valuation_history()` helper and the underlying `akshare` source. When that history is unavailable, `valuation_percentile` degrades to `None`, which is intentional and keeps v1 deterministic rather than inventing a baseline.
- `smart_dca` current action is intentionally derived from target-weight changes instead of cash-tranche execution because the brief explicitly requires action to come from target-weight changes, not backtest liquidation artifacts.

## Files Changed

- [market_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/market_context.py)
- [strategy_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/strategy_context.py)
- [models.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/opportunity_center/models.py)
- [hstech_best.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/src/paper_trading/hstech_best.py)
- [test_market_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_market_context.py)
- [test_strategy_context.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_strategy_context.py)
- [test_models.py](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/agent/tests/opportunity_center/test_models.py)
- [task-4-report.md](/Users/lianghuang/Vibe-Trading/.worktrees/watchlist-opportunity-center/.superpowers/sdd/task-4-report.md)

## Review Findings Fix: 2026-06-30

### Changes

- OOS metrics now prepend the last equity observation before the first OOS bar. `pct_change`, Sharpe, and max drawdown therefore include the train/OOS boundary move and boundary peak, while total return remains boundary-to-final.
- Strategy backtests now preserve their completed trade records. OOS metric calculation passes only trades whose entry and exit are both inside the OOS window.
- HK PB fallback now requires at least 30 positive finite observations, matching PE. Non-finite values cannot satisfy the minimum, and PE/PB histories below the threshold return `None`.

### RED Evidence

1. Added deterministic seam, trade-window, and PB-threshold regressions, then ran:
   - `uv run pytest agent/tests/opportunity_center/test_strategy_context.py agent/tests/opportunity_center/test_market_context.py -v`
2. Result: `3 failed, 14 passed in 5.12s`.
3. Expected failures:
   - `_oos_metrics()` did not accept or filter trades and omitted the pre-OOS boundary point.
   - PB fallback returned `100.0` for 28 finite positive values plus `inf`, instead of `None`.

### GREEN Evidence

1. Re-ran focused Task 4 tests after the fixes:
   - `uv run pytest agent/tests/opportunity_center/test_strategy_context.py agent/tests/opportunity_center/test_market_context.py -v`
   - Result: `17 passed in 5.03s`.
2. The seam regression compares directly with `calc_metrics()` over `[boundary + OOS]`. Its fixed equity path includes the first OOS move from `120` to `90`, verifies boundary-to-final return, and verifies max drawdown is `-0.325` rather than the boundary-omitting `-0.25`.
3. Ran the complete requested regression set:
   - `uv run pytest agent/tests/opportunity_center/test_strategy_context.py agent/tests/opportunity_center/test_market_context.py agent/tests/test_paper_trading_lookahead.py agent/tests/opportunity_center/test_models.py agent/tests/test_hstech_best_strategy.py -v`
   - Result: `34 passed in 5.05s`.

### Review

- Re-read the changed metric path and tests after GREEN. The boundary point is used only as the initial OOS equity observation; training remains all rows before the final 252 OOS bars, and selected-strategy evaluation remains restricted to data at or before `as_of`.
- No unresolved Task 4 correctness concerns found.
