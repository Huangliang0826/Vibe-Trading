# Unified Market Metrics Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every stock price chart and portfolio performance surface use one backend-owned, validated definition of adjusted prices, interval return, daily-DCA return, maximum loss, maximum drawdown, and volume.

**Architecture:** Add a pure `src.market_metrics` package for validation and financial arithmetic, then place a service/cache adapter between existing loaders and `/watchlist/history`. Extend the existing response rather than creating a parallel endpoint, migrate shared React charts to render server metrics, and reuse the same loss/drawdown primitives in paper trading.

**Tech Stack:** Python 3.11+, pandas, FastAPI, pytest, React 18, TypeScript, ECharts, Vitest.

## Global Constraints

- Historical chart and return calculations default to adjusted prices.
- `1D` uses previous official adjusted close to the latest compatible price.
- Longer periods use the final trading close before the requested range as baseline.
- Maximum loss is relative to cumulative invested capital; maximum drawdown remains a separate peak-to-trough metric.
- Volume remains nullable in the provider's original unit; missing volume is never converted to zero.
- Frontend code must not calculate financial performance metrics after migration.
- Invalid data and unavailable baselines produce `null` metrics with reason codes, not fabricated zeroes.
- Preserve unrelated uncommitted scanner changes throughout execution.

---

## File Structure

- Create `agent/src/market_metrics/__init__.py`: public exports and `FORMULA_VERSION`.
- Create `agent/src/market_metrics/models.py`: typed bar, quote, quality, metric, and response dataclasses.
- Create `agent/src/market_metrics/validation.py`: deterministic OHLCV quality checks.
- Create `agent/src/market_metrics/calculations.py`: pure interval, DCA, maximum-loss, and drawdown functions.
- Create `agent/src/market_metrics/service.py`: canonical response assembly and baseline handling.
- Create `agent/src/market_metrics/cache.py`: atomic versioned metric response cache.
- Create `agent/tests/market_metrics/`: hand-calculated unit and contract tests.
- Modify `agent/api_server.py`: adapt existing history fetching and route response.
- Modify `agent/src/api/market_data_routes.py`: keep the market-data route boundary explicit.
- Modify `agent/backtest/metrics.py`: delegate common loss/drawdown arithmetic to the shared engine.
- Modify `frontend/src/lib/api.ts`: add the unified response contract.
- Modify `frontend/src/components/charts/PriceHistoryChart.tsx`: render backend metrics and quality state only.
- Modify `frontend/src/pages/Overview.tsx`: store/cache and pass the complete history response.
- Modify `frontend/src/pages/HSTech.tsx`: consume the same response contract.
- Modify focused frontend and backend tests listed in each task.

### Task 1: Typed OHLCV Contract and Quality Validation

**Files:**
- Create: `agent/src/market_metrics/__init__.py`
- Create: `agent/src/market_metrics/models.py`
- Create: `agent/src/market_metrics/validation.py`
- Test: `agent/tests/market_metrics/test_validation.py`

**Interfaces:**
- Produces: `MarketBar`, `LatestQuote`, `QualityIssue`, `DataQuality`, `validate_bars(bars, *, expected_latest_date=None) -> DataQuality`.
- Consumers: Tasks 2-5.

- [ ] **Step 1: Write failing validation tests**

```python
def test_missing_volume_is_warning_not_zero():
    quality = validate_bars([
        MarketBar("2026-01-02", 100, 101, 99, 100, None),
        MarketBar("2026-01-05", 101, 103, 100, 102, 1200),
    ])
    assert quality.status == "warning"
    assert quality.issues[0].code == "missing_volume"

def test_duplicate_date_and_invalid_ohlc_block_metrics():
    bars = [
        MarketBar("2026-01-02", 100, 90, 99, 100, 1000),
        MarketBar("2026-01-02", 100, 101, 99, 100, 1000),
    ]
    quality = validate_bars(bars)
    assert quality.status == "invalid"
    assert {issue.code for issue in quality.issues} == {"duplicate_timestamp", "invalid_ohlc"}
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics/test_validation.py`

Expected: collection fails because `src.market_metrics` does not exist.

- [ ] **Step 3: Implement immutable models and validation**

Use dataclasses with explicit nullable volume and JSON-safe `to_dict()` methods. Validation must sort no input silently; it reports `unsorted_timestamp`, `duplicate_timestamp`, `non_positive_price`, `invalid_ohlc`, `negative_volume`, `missing_volume`, and `stale_data`. `DataQuality.status` is `invalid` when any blocking issue exists, `warning` for non-blocking issues, otherwise `valid`.

```python
FORMULA_VERSION = "market-metrics-v1"

@dataclass(frozen=True)
class MarketBar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None

def validate_bars(
    bars: Sequence[MarketBar], *, expected_latest_date: date | None = None
) -> DataQuality:
    issues = collect_quality_issues(bars, expected_latest_date=expected_latest_date)
    status = "invalid" if any(item.blocking for item in issues) else "warning" if issues else "valid"
    return DataQuality(status=status, issues=tuple(issues))
```

- [ ] **Step 4: Run focused and scanner tests**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics/test_validation.py agent/tests/scanner`

Expected: all tests pass; scanner tests confirm nullable-volume work did not affect scanner tracking.

- [ ] **Step 5: Commit the validation boundary**

```bash
git add agent/src/market_metrics agent/tests/market_metrics/test_validation.py
git commit -m "Add market data quality validation"
```

### Task 2: Pure Financial Metric Calculations

**Files:**
- Create: `agent/src/market_metrics/calculations.py`
- Test: `agent/tests/market_metrics/test_calculations.py`
- Modify: `agent/src/market_metrics/__init__.py`

**Interfaces:**
- Consumes: validated `MarketBar` values from Task 1.
- Produces: `interval_return`, `daily_dca_metrics`, `maximum_loss`, and `maximum_drawdown`.

- [ ] **Step 1: Write hand-calculated failing tests**

```python
def test_interval_return_uses_explicit_baseline():
    assert interval_return(100.0, 121.0) == pytest.approx(0.21)

def test_daily_dca_loss_is_relative_to_contributions():
    result = daily_dca_metrics([100.0, 50.0, 80.0])
    assert result.total_return == pytest.approx(0.1333333333)
    assert result.max_loss == pytest.approx(-0.25)
    assert result.contribution_count == 3

def test_maximum_loss_and_drawdown_are_not_synonyms():
    account = [100.0, 150.0, 120.0]
    principal = [100.0, 100.0, 100.0]
    assert maximum_loss(account, principal) == 0.0
    assert maximum_drawdown(account) == pytest.approx(-0.20)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics/test_calculations.py`

Expected: import failure for calculation functions.

- [ ] **Step 3: Implement pure arithmetic without pandas side effects**

```python
def maximum_loss(values: Sequence[float], principals: Sequence[float]) -> float | None:
    if not values or len(values) != len(principals):
        return None
    returns = [value / principal - 1 for value, principal in zip(values, principals) if principal > 0]
    return min(returns) if returns else None

def maximum_drawdown(values: Sequence[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1 if peak > 0 else 0.0)
    return worst
```

Implement DCA with explicit accumulated units and one equal contribution at each supplied trading close. Reject non-positive prices instead of skipping them.

- [ ] **Step 4: Run exact arithmetic tests**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics/test_calculations.py`

Expected: all tests pass with exact fixture values.

- [ ] **Step 5: Commit the calculation core**

```bash
git add agent/src/market_metrics agent/tests/market_metrics/test_calculations.py
git commit -m "Add canonical market metric calculations"
```

### Task 3: Baseline-Aware Metrics Service

**Files:**
- Create: `agent/src/market_metrics/service.py`
- Test: `agent/tests/market_metrics/test_service.py`
- Modify: `agent/src/market_metrics/models.py`
- Modify: `agent/src/market_metrics/__init__.py`

**Interfaces:**
- Consumes: canonical bars, period, symbol, market, currency, source, optional compatible quote.
- Produces: `build_market_metrics_response(*, symbol, market, currency, period, requested_start, bars, source, quote=None) -> MarketMetricsResponse`.

- [ ] **Step 1: Write failing service contract tests**

Cover these explicit cases:

```python
def test_one_year_uses_pre_range_bar_but_dca_starts_inside_range():
    response = build_market_metrics_response(
        symbol="AAPL", market="us", currency="USD", period="1Y",
        requested_start=date(2025, 1, 3), bars=fixture_bars(), source="fixture",
    )
    assert response.baseline.date == "2025-01-02"
    assert response.metrics.interval_return_pct == pytest.approx(21.0)
    assert response.metrics.dca.contribution_count == 2

def test_missing_baseline_returns_null_with_reason():
    response = build_market_metrics_response(
        symbol="AAPL", market="us", currency="USD", period="1Y",
        requested_start=date(2025, 1, 3), bars=bars_without_prior_close,
        source="fixture",
    )
    assert response.metrics.interval_return_pct is None
    assert response.metric_reasons["interval_return_pct"] == "missing_baseline"

def test_incompatible_live_quote_is_not_mixed_with_adjusted_history():
    response = build_market_metrics_response(
        symbol="AAPL", market="us", currency="USD", period="1Y",
        requested_start=date(2025, 1, 3), bars=fixture_bars(), source="fixture",
        quote=LatestQuote(price=130, prev_close=129, adjustment="raw"),
    )
    assert response.endpoint.source == "adjusted_history"
```

- [ ] **Step 2: Run the service tests and verify RED**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics/test_service.py`

Expected: `build_market_metrics_response` is missing.

- [ ] **Step 3: Implement response assembly**

The response must expose `formula_version`, `adjustment="adjusted"`, baseline and endpoint observations, chart series, nullable volume, metrics, per-field reason codes, and `DataQuality`. `1D` may use a compatible quote and its official previous close; longer periods end at adjusted history. Invalid quality blocks all affected calculations.

- [ ] **Step 4: Run all market-metric tests**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics`

Expected: all validation, arithmetic, and response-contract tests pass.

- [ ] **Step 5: Commit the service contract**

```bash
git add agent/src/market_metrics agent/tests/market_metrics
git commit -m "Build baseline-aware market metric responses"
```

### Task 4: Versioned Atomic Response Cache

**Files:**
- Create: `agent/src/market_metrics/cache.py`
- Test: `agent/tests/market_metrics/test_cache.py`

**Interfaces:**
- Produces: `MarketMetricsCache.get(key: str, *, source_revision: str) -> MarketMetricsResponse | None`, `MarketMetricsCache.put(key: str, response: MarketMetricsResponse, *, source_revision: str) -> bool`, and `make_cache_key(market: str, symbol: str, period: str, adjustment: str) -> str`.
- Storage root: `~/.vibe-trading/market_metrics/`, overridable in tests.

- [ ] **Step 1: Write failing cache tests**

Test isolation by market/symbol/period, invalidation on `FORMULA_VERSION`, invalidation on source revision, atomic replacement, and refusal to cache `quality.status == "invalid"`.

```python
def test_formula_version_invalidates_cached_metrics(tmp_path):
    cache = MarketMetricsCache(tmp_path, formula_version="v1")
    cache.put("us:AAPL:1Y", valid_response, source_revision="2026-07-03")
    assert MarketMetricsCache(tmp_path, formula_version="v2").get(
        "us:AAPL:1Y", source_revision="2026-07-03"
    ) is None
```

- [ ] **Step 2: Run cache tests and verify RED**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics/test_cache.py`

Expected: cache class import fails.

- [ ] **Step 3: Implement JSON cache with temp-file replacement**

Write metadata and response in one JSON document using `allow_nan=False`, `flush`, `fsync`, and `Path.replace`. Treat malformed JSON as a miss and retain the last valid entry when a new response is invalid.

- [ ] **Step 4: Run cache and service tests**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics`

Expected: all tests pass.

- [ ] **Step 5: Commit cache support**

```bash
git add agent/src/market_metrics/cache.py agent/tests/market_metrics/test_cache.py
git commit -m "Cache versioned market metric responses"
```

### Task 5: Integrate the Existing History API

**Files:**
- Modify: `agent/api_server.py:2140-2345`
- Modify: `agent/src/api/market_data_routes.py`
- Modify: `agent/tests/test_price_history_periods.py`
- Create: `agent/tests/market_metrics/test_history_api.py`

**Interfaces:**
- Consumes: `build_market_metrics_response` and `MarketMetricsCache`.
- Produces: enriched `GET /watchlist/history` response while retaining `code`, `name`, `period`, and `bars` for compatibility.

- [ ] **Step 1: Write failing API tests**

Assert that the route returns `adjustment`, `formula_version`, `baseline`, `endpoint`, `metrics`, and `data_status`; volume is `null` when absent; missing baselines return HTTP 200 with a nullable metric and reason; invalid OHLC returns HTTP 200 with `quality="invalid"` rather than a fake percentage.

- [ ] **Step 2: Add regression tests for adjusted-source behavior**

Replace the current A-share expectation that silently falls back to raw prices. A non-positive adjusted series must return invalid quality with reason `non_positive_price`; it must not switch price basis. The test must assert `adjustment == "adjusted"` and prohibit mixing raw fallback history with adjusted metrics.

- [ ] **Step 3: Run API tests and verify RED**

Run: `PYTHONPATH=agent pytest -q agent/tests/test_price_history_periods.py agent/tests/market_metrics/test_history_api.py`

Expected: enriched fields are missing and the raw-fallback regression fails.

- [ ] **Step 4: Adapt `_fetch_price_history` and `get_watchlist_history`**

Make `_df_to_bars` preserve nullable volume and full OHLC when available. Return loader/source metadata and requested range boundaries. Pass canonical bars to the service, then cache only validated responses. Keep the existing route URL and compatibility fields so historical-event consumers continue to work.

- [ ] **Step 5: Run backend regression suites**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics agent/tests/test_price_history_periods.py agent/tests/test_market_detection.py agent/tests/test_forecast.py agent/tests/test_hstech_best_strategy.py`

Expected: all selected suites pass.

- [ ] **Step 6: Commit API integration**

```bash
git add agent/api_server.py agent/src/api/market_data_routes.py agent/src/market_metrics agent/tests/market_metrics agent/tests/test_price_history_periods.py
git commit -m "Serve validated market metrics with price history"
```

### Task 6: Migrate the Shared Price Chart and Overview

**Files:**
- Modify: `frontend/src/lib/api.ts:375-380,505-520`
- Modify: `frontend/src/components/charts/PriceHistoryChart.tsx`
- Modify: `frontend/src/components/charts/__tests__/PriceHistoryChart.test.ts`
- Modify: `frontend/src/pages/Overview.tsx:400-525`
- Modify: `frontend/src/lib/overview-price-cache.ts`
- Modify: `frontend/src/lib/__tests__/overview-price-cache.test.ts`

**Interfaces:**
- Consumes: backend `WatchlistHistoryResponse.metrics`, `.baseline`, `.endpoint`, and `.data_status`.
- Produces: a chart that renders supplied values and never recomputes them.

- [ ] **Step 1: Write failing frontend contract tests**

```typescript
it("renders backend metrics without recomputing from plotted bars", () => {
  render(<PriceHistoryChart history={history({ interval_return_pct: 12.34 })} period="1Y" onPeriodChange={() => undefined} />);
  expect(screen.getByText("+12.34%")).toBeInTheDocument();
});

it("shows unavailable instead of zero for a missing baseline", () => {
  render(<PriceHistoryChart history={history({ interval_return_pct: null }, "missing_baseline")} period="1Y" onPeriodChange={() => undefined} />);
  expect(screen.getByText("数据不足")).toBeInTheDocument();
});
```

Delete tests importing `computeDailyDca`; the replacement test must prove the browser cannot diverge from backend values.

- [ ] **Step 2: Run Vitest and verify RED**

Run: `npm --prefix frontend test -- --run src/components/charts/__tests__/PriceHistoryChart.test.ts src/lib/__tests__/overview-price-cache.test.ts`

Expected: the old component accepts bars and computes its own metrics.

- [ ] **Step 3: Add TypeScript types and migrate the component**

Change the primary prop to `history: WatchlistHistoryResponse | null`. Remove `computeDailyDca` and `computeDrawdown`. Use backend interval return, DCA return, DCA maximum loss, buy-and-hold maximum loss, and maximum drawdown. Tooltip percentages use the backend baseline value. Render quality warnings compactly and do not render volume bars for null observations.

- [ ] **Step 4: Migrate Overview state and cache**

Store/cache the complete response, not only `bars`. Bump the overview cache namespace so legacy payloads cannot masquerade as unified responses. Historical events continue receiving `history.bars`.

- [ ] **Step 5: Run focused frontend tests and build**

Run: `npm --prefix frontend test -- --run src/components/charts/__tests__/PriceHistoryChart.test.ts src/lib/__tests__/overview-price-cache.test.ts src/pages/__tests__/OverviewHistoricalEvents.test.ts src/pages/__tests__/OverviewIndexCards.test.tsx`

Run: `npm --prefix frontend run build`

Expected: tests and TypeScript build pass.

- [ ] **Step 6: Commit the first UI migration**

```bash
git add frontend/src/lib/api.ts frontend/src/components/charts/PriceHistoryChart.tsx frontend/src/components/charts/__tests__/PriceHistoryChart.test.ts frontend/src/pages/Overview.tsx frontend/src/lib/overview-price-cache.ts frontend/src/lib/__tests__/overview-price-cache.test.ts
git commit -m "Render canonical metrics in overview charts"
```

### Task 7: Migrate HSTech and Align Strategy Markers

**Files:**
- Modify: `frontend/src/pages/HSTech.tsx:1050-1140,1400-1440`
- Modify: `frontend/src/pages/__tests__/ForecastRobustStrategy.test.tsx`
- Create: `frontend/src/pages/__tests__/HSTechPriceMetrics.test.tsx`
- Modify: `agent/src/paper_trading/hstech_best.py`
- Modify: `agent/tests/test_hstech_best_strategy.py`

**Interfaces:**
- Consumes: unified history response and adjusted chart dates.
- Produces: HSTech chart metrics and strategy markers tied to the same date/price series.

- [ ] **Step 1: Write failing HSTech tests**

Mock a history payload whose backend metric deliberately differs from the bar-derived number and assert the backend value is displayed. Add a strategy trade on a non-trading date and assert the backend normalizer maps it to the next available chart session without changing the execution price.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `PYTHONPATH=agent pytest -q agent/tests/test_hstech_best_strategy.py`

Run: `npm --prefix frontend test -- --run src/pages/__tests__/HSTechPriceMetrics.test.tsx src/pages/__tests__/ForecastRobustStrategy.test.tsx`

Expected: HSTech still passes only bars/quote and marker alignment lacks a shared-session assertion.

- [ ] **Step 3: Migrate HSTech history state**

Replace separate bar-derived chart metrics with the complete response and pass it to `PriceHistoryChart`. Keep valuation state independent. Normalize best-strategy marker dates against the history response's adjusted daily sessions before rendering.

- [ ] **Step 4: Run HSTech and forecast regressions**

Run: `PYTHONPATH=agent pytest -q agent/tests/test_hstech_best_strategy.py agent/tests/test_forecast_strategy.py agent/tests/test_forecast_robust_cache.py`

Run: `npm --prefix frontend test -- --run src/pages/__tests__/HSTechPriceMetrics.test.tsx src/pages/__tests__/ForecastRobustStrategy.test.tsx src/components/charts/__tests__/ForecastChart.test.ts`

Expected: all selected tests pass.

- [ ] **Step 5: Commit HSTech migration**

```bash
git add agent/src/paper_trading/hstech_best.py agent/tests/test_hstech_best_strategy.py frontend/src/pages/HSTech.tsx frontend/src/pages/__tests__/HSTechPriceMetrics.test.tsx frontend/src/pages/__tests__/ForecastRobustStrategy.test.tsx
git commit -m "Align HSTech metrics and strategy markers"
```

### Task 8: Reuse Loss and Drawdown Primitives in Paper Trading

**Files:**
- Modify: `agent/backtest/metrics.py:170-235`
- Modify: `agent/src/paper_trading/executor.py:55-80,645-660`
- Modify: `agent/tests/test_metrics.py`
- Create: `agent/tests/test_paper_trading_cashflows.py`
- Modify: `frontend/src/pages/PaperTrading.tsx`

**Interfaces:**
- Consumes: `maximum_loss(values, principals)` and `maximum_drawdown(values)` from Task 2.
- Produces: consistent `max_loss` and `max_drawdown` for fixed-capital and externally funded portfolios.

- [ ] **Step 1: Write failing cash-flow tests**

```python
def test_external_contributions_change_max_loss_denominator():
    equity = pd.Series([100, 140, 170], index=dates)
    principal = pd.Series([100, 150, 200], index=dates)
    metrics = calc_metrics(equity, [], 100, invested_principal=principal)
    assert metrics["max_loss"] == pytest.approx(-0.15)
    assert metrics["max_drawdown"] == 0.0
```

Also retain the existing fixed-capital test where a peak-to-trough decline does not imply a loss below principal.

- [ ] **Step 2: Run metrics tests and verify RED**

Run: `PYTHONPATH=agent pytest -q agent/tests/test_metrics.py agent/tests/test_paper_trading_cashflows.py`

Expected: `calc_metrics` has no `invested_principal` argument.

- [ ] **Step 3: Delegate arithmetic to shared functions**

Add optional `invested_principal: pd.Series | None = None` to `calc_metrics`. Reindex/forward-fill explicit contribution ledgers only; fixed-capital callers continue using `initial_cash`. Persist both `max_loss` and `max_drawdown`. Do not rename one into the other in `PaperTrading.tsx`.

- [ ] **Step 4: Run paper-trading suites**

Run: `PYTHONPATH=agent pytest -q agent/tests/test_metrics.py agent/tests/test_paper_trading_cashflows.py agent/tests/test_paper_trading_lookahead.py agent/tests/test_paper_trading_robust.py`

Expected: all tests pass.

- [ ] **Step 5: Commit portfolio metric unification**

```bash
git add agent/backtest/metrics.py agent/src/paper_trading/executor.py agent/tests/test_metrics.py agent/tests/test_paper_trading_cashflows.py frontend/src/pages/PaperTrading.tsx
git commit -m "Unify paper trading loss and drawdown metrics"
```

### Task 9: Repository Guard and End-to-End Acceptance

**Files:**
- Create: `agent/tests/market_metrics/test_frontend_metric_ownership.py`
- Create: `agent/tests/market_metrics/fixtures/us_split.json`
- Create: `agent/tests/market_metrics/fixtures/hk_sparse.json`
- Create: `agent/tests/market_metrics/fixtures/cn_holiday.json`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: automated proof that page-level financial formulas do not return.

- [ ] **Step 1: Add cross-market acceptance fixtures**

Fixtures contain small, licensed synthetic sequences representing a US split-adjusted series, nullable HK volume/suspension gap, and an A-share holiday boundary. Expected baseline, interval return, DCA return, maximum loss, and drawdown are stored as explicit values.

- [ ] **Step 2: Add frontend ownership guard**

The test scans `frontend/src/pages` and `frontend/src/components/charts` and fails on new implementations of known formulas such as `.cummax`, `wealth / contributed`, `close / firstClose - 1`, or exported `computeDailyDca`. Exempt formatting-only percentage multiplication.

- [ ] **Step 3: Run the complete verification matrix**

Run: `PYTHONPATH=agent pytest -q agent/tests/market_metrics agent/tests/test_price_history_periods.py agent/tests/test_metrics.py agent/tests/test_paper_trading_lookahead.py agent/tests/test_paper_trading_robust.py agent/tests/test_forecast.py agent/tests/test_forecast_strategy.py agent/tests/test_hstech_best_strategy.py`

Run: `npm --prefix frontend test -- --run src/components/charts/__tests__/PriceHistoryChart.test.ts src/pages/__tests__/HSTechPriceMetrics.test.tsx src/pages/__tests__/OverviewHistoricalEvents.test.ts src/pages/__tests__/ForecastRobustStrategy.test.tsx src/lib/__tests__/overview-price-cache.test.ts`

Run: `npm --prefix frontend run build`

Expected: all commands exit zero; no TypeScript errors; only the existing Vite chunk-size warning is acceptable.

- [ ] **Step 4: Perform local API smoke checks**

After restarting the backend, request one symbol per market and verify response fields:

```bash
curl -fsS 'http://127.0.0.1:8899/watchlist/history?code=AAPL&period=1Y&market=us'
curl -fsS 'http://127.0.0.1:8899/watchlist/history?code=0700&period=1Y&market=hk'
curl -fsS 'http://127.0.0.1:8899/watchlist/history?code=600519&period=1Y&market=cn'
```

Each response must include `formula_version`, explicit baseline/endpoint, non-null interval return when data is complete, distinct maximum-loss/drawdown fields, and quality/source timestamps.

- [ ] **Step 5: Update product history and commit acceptance coverage**

Document the unified metric definitions and cache invalidation behavior in `CHANGELOG.md`.

```bash
git add agent/tests/market_metrics CHANGELOG.md
git commit -m "Verify unified market metrics across markets"
```

## Final Review Checklist

- [ ] Confirm `git diff --check` is clean.
- [ ] Confirm unrelated scanner files were neither reverted nor folded into these commits.
- [ ] Confirm Overview and HSTech display identical results for the same symbol/range payload.
- [ ] Confirm null volume remains null through Python, JSON, TypeScript, and ECharts.
- [ ] Confirm `1D` uses official previous close and longer periods expose their prior-session baseline.
- [ ] Confirm DCA starts inside the selected range rather than investing on the baseline-only observation.
- [ ] Confirm maximum loss and maximum drawdown differ correctly in the acceptance fixture.
- [ ] Confirm invalid data cannot overwrite a valid cache entry.
