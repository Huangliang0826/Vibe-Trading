# Task 1 Report: Contracts, Source Catalog, and Attribution

## Implementation

- Created `agent/src/opportunity_center/__init__.py` to expose the public opportunity-center contract surface and re-export `strategy_params`.
- Created `agent/src/opportunity_center/models.py` with:
  - `SCORE_VERSION = "opportunity-v1"`
  - `STRATEGY_VERSION = "oos-holdout-v1"`
  - strict Pydantic contracts for `OpportunityItem`, `OpportunityDetail`, `OpportunityList`, `RefreshJob`, `NewsArticle`, `NewsImpact`, `StockContext`, `StrategyContext`, `MarketContext`, and `DimensionScores`
  - closed enums/literals from the brief and `Field(ge=0, le=100)` validation on score, strength, confidence, and percentile-style fields
- Vendored `agent/src/opportunity_center/sources.json` by copying `/Users/lianghuang/Desktop/investment-news/sources.json` verbatim.
- Added `agent/src/opportunity_center/THIRD_PARTY_NOTICE.md` with the full upstream MIT license text and copyright line.
- Updated root `NOTICE` with the required opportunity-center attribution paragraph.
- Updated `pyproject.toml` package data to include:
  - `"src.opportunity_center" = ["*.json", "*.md"]`
- Renamed `_strategy_params()` to public `strategy_params()` in `agent/src/paper_trading/hstech_best.py`, updated the internal call site, and preserved `_strategy_params = strategy_params` as a compatibility alias.

## Tests / Results

- Focused contract tests:
  - `uv run pytest agent/tests/opportunity_center/test_models.py agent/tests/test_hstech_best_strategy.py -v`
  - Result: `11 passed in 0.49s`
- Exact source-catalog copy check:
  - `cmp -s /Users/lianghuang/Desktop/investment-news/sources.json agent/src/opportunity_center/sources.json && echo MATCH`
  - Result: `MATCH`
- Diff hygiene:
  - `git diff --check`
  - Result: no whitespace or patch-format issues

## RED / GREEN Evidence

### RED

1. Added `agent/tests/opportunity_center/test_models.py` first.
2. Ran:
   - `uv run pytest agent/tests/opportunity_center/test_models.py -v`
3. Observed expected failure:
   - `ModuleNotFoundError: No module named 'src.opportunity_center'`
4. Added a second contract test for the public strategy helper, then ran:
   - `uv run pytest agent/tests/opportunity_center/test_models.py agent/tests/test_hstech_best_strategy.py -v`
5. Observed expected failures:
   - `ModuleNotFoundError: No module named 'src.opportunity_center'`
   - `ImportError: cannot import name 'strategy_params'`

### GREEN

1. Implemented the new opportunity-center package, vendored source catalog + attribution, and exposed `strategy_params()`.
2. Re-ran:
   - `uv run pytest agent/tests/opportunity_center/test_models.py agent/tests/test_hstech_best_strategy.py -v`
3. Result:
   - all 11 focused tests passed

## Files Changed

- `agent/src/opportunity_center/__init__.py`
- `agent/src/opportunity_center/models.py`
- `agent/src/opportunity_center/sources.json`
- `agent/src/opportunity_center/THIRD_PARTY_NOTICE.md`
- `agent/src/paper_trading/hstech_best.py`
- `agent/tests/opportunity_center/test_models.py`
- `agent/tests/test_hstech_best_strategy.py`
- `pyproject.toml`
- `NOTICE`

## Self-Review

- The public contract surface is intentionally narrow and stable: literals close the vocabularies, `extra="forbid"` keeps the payload shapes strict, and the version constants are exported explicitly.
- I kept timestamp/date fields as strings because the brief uses string contracts and later tasks are more likely to rely on wire-format stability than datetime coercion.
- `strategy_params()` remains backward-compatible through the `_strategy_params` alias, so existing private callers do not break.
- I verified the vendored `sources.json` is byte-for-byte identical to the upstream file rather than relying on a manual paste.
- I did not touch the unrelated baseline exception in `agent/tests/test_forecast_strategy.py::test_backtest_shapes_and_benchmark`.

## Concerns

- No functional concern blocks this task.
- The new package-data entry is covered by configuration review, but not by a build/install integration test in this task’s focused suite.
