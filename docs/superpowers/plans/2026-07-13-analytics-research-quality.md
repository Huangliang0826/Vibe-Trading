# Analytics Research Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add statistically honest Scanner, Forecast, Backtest, and Paper Trading quality trends to the working analytics system.

**Architecture:** Domain adapters read existing authoritative outputs and convert them into deduplicated `quality` events; they never reimplement financial metrics. The analytics statistics layer adds deterministic bootstrap intervals and rolling quality views, and the React research view renders sample size, uncertainty, market/horizon filters, and explicit unavailable reasons.

**Tech Stack:** Existing analytics SQLite pipeline, Python stdlib statistics/random, existing Scanner/Forecast/Backtest/Paper Trading modules, FastAPI, React, TypeScript, ECharts, pytest, Vitest.

## Global Constraints

- Complete `2026-07-13-analytics-foundation-usage-system.md` first.
- Existing domain modules remain the authority for returns, Sharpe, drawdown, loss, calibration, and direction accuracy.
- Every research point carries subject, market, horizon, sample count, formula version, and `as_of`.
- Rates use 95% Wilson intervals; return/strategy differences use seeded percentile bootstrap with 2,000 resamples.
- Quality/development raw events and daily quality aggregates retain indefinitely.
- Missing matches or insufficient samples return `null` plus a reason; never infer compatibility.
- Follow TDD and commit each independently testable adapter.

---

## File Structure

- `agent/src/analytics/quality.py`: quality-event factory and observation identity.
- `agent/src/analytics/quality_adapters.py`: Scanner, Forecast, Backtest, and Paper Trading adapters.
- `agent/src/analytics/quality_identity.py`: comparable strategy identity.
- `agent/src/analytics/statistics.py`: seeded bootstrap extension.
- `agent/src/analytics/rollup.py`: daily research aggregation.
- `frontend/src/components/analytics/ResearchQualityView.tsx`: research filters, cards, and trends.

### Task 1: Deterministic Quality Events and Bootstrap Intervals

**Files:**
- Create: `agent/src/analytics/quality.py`
- Modify: `agent/src/analytics/statistics.py`
- Create: `agent/tests/analytics/test_quality.py`
- Modify: `agent/tests/analytics/test_statistics.py`

**Interfaces:**
- Produces: `make_quality_event(*, subject_type: str, subject_id: str, market: str, horizon: str, regime: str, metric_name: str, metric_value: float | None, sample_count: int, formula_version: str, as_of: date, interval_low: float | None = None, interval_high: float | None = None, reason: str | None = None) -> AnalyticsEvent`, `bootstrap_interval(values: list[float], statistic: Literal["mean", "sharpe"], resamples: int = 2000, seed: int = 1729) -> tuple[float, float]`.
- Consumes: Phase 1 `AnalyticsEvent` and collector metadata allowlist.

- [ ] **Step 1: Write failing deterministic identity tests**

```python
from datetime import date

from src.analytics.quality import make_quality_event
from src.analytics.statistics import bootstrap_interval


def test_quality_event_id_is_stable_per_observation():
    kwargs = dict(
        subject_type="forecast", subject_id="AAPL", market="us", horizon="63d",
        regime="all", metric_name="directional_accuracy", metric_value=0.56,
        sample_count=25, formula_version="forecast.calibration.v1", as_of=date(2026, 7, 13),
    )
    assert make_quality_event(**kwargs).event_id == make_quality_event(**kwargs).event_id


def test_seeded_bootstrap_is_repeatable():
    values = [0.01, 0.02, -0.01, 0.03, 0.0]
    first = bootstrap_interval(values, statistic="mean", resamples=2000, seed=1729)
    assert first == bootstrap_interval(values, statistic="mean", resamples=2000, seed=1729)
    assert first[0] <= sum(values) / len(values) <= first[1]
```

- [ ] **Step 2: Run tests and verify missing functions**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_quality.py tests/analytics/test_statistics.py -v`

Expected: FAIL on missing `quality` module and `bootstrap_interval`.

- [ ] **Step 3: Implement exact observation identity and bootstrap behavior**

Build the event ID as SHA-256 of canonical JSON containing subject type/id, market, horizon, regime, metric name, formula version, and `as_of`; prefix the first 32 hex characters with `quality-`. Put the same fields plus nullable `metric_value`, `sample_count`, optional `interval_low`/`interval_high`, optional machine-readable `reason`, and `as_of` in allowlisted metadata. Set `feature=subject_type`, `action=metric_name`, and use `outcome="success"` only when the value is available; otherwise use `outcome="unknown"`.

`bootstrap_interval` accepts only `statistic="mean"` or `"sharpe"`, rejects fewer than two finite values with `ValueError`, samples with `random.Random(seed).choices`, sorts 2,000 statistics, and returns the 2.5th/97.5th nearest-rank values.

- [ ] **Step 4: Run tests and commit**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_quality.py tests/analytics/test_statistics.py -v`

Expected: all tests PASS.

```bash
git add agent/src/analytics/quality.py agent/src/analytics/statistics.py agent/tests/analytics
git commit -m "feat: add research quality observations"
```

### Task 2: Scanner and Forecast Quality Adapters

**Files:**
- Create: `agent/src/analytics/quality_adapters.py`
- Create: `agent/tests/analytics/test_quality_adapters.py`
- Modify: `agent/src/api/scan_routes.py`
- Modify: `agent/api_server.py`

**Interfaces:**
- Produces: `ScannerQualityAdapter.collect(universe, provider=None)`, `ForecastQualityAdapter.from_calibration(payload)`.
- Consumes: `scanner.tracking.load_all_tracking`, `scanner.tracking.compute_accuracy`, existing Forecast calibration payload, `AnalyticsCollector.submit`.

- [ ] **Step 1: Write failing Scanner mapping tests**

```python
def test_scanner_adapter_maps_each_horizon_without_recomputing(monkeypatch):
    monkeypatch.setattr("src.analytics.quality_adapters.load_all_tracking", lambda universe: [object()])
    monkeypatch.setattr("src.analytics.quality_adapters.compute_accuracy", lambda records, provider=None: {
        "horizons": {"fwd_5d": {"n": 40, "mean": 1.2, "hit_rate": 0.575, "spread": 0.8}},
        "timeseries": [],
    })
    events = ScannerQualityAdapter().collect("sp500")
    values = {(event.metadata["horizon"], event.metadata["metric_name"]): event.metadata["metric_value"] for event in events}
    assert values[("5d", "hit_rate")] == 0.575
    assert values[("5d", "mean_forward_return_pct")] == 1.2
    assert values[("5d", "top_bottom_spread_pct")] == 0.8
```

- [ ] **Step 2: Write failing Forecast mapping tests**

```python
def test_forecast_adapter_maps_calibration_payload():
    payload = {
        "code": "AAPL", "market": "us", "bt_horizon": 63,
        "directional_accuracy": {"model": 0.56, "n": 25},
        "mae": {"model": 3.2}, "interval_coverage_80": 0.76,
        "interval_score_skill": 0.11, "mean_interval_width_pct": 8.4,
    }
    events = ForecastQualityAdapter().from_calibration(payload)
    by_metric = {event.metadata["metric_name"]: event for event in events}
    assert by_metric["directional_accuracy"].metadata["metric_value"] == 0.56
    assert by_metric["mae"].metadata["metric_value"] == 3.2
    assert all(event.metadata["formula_version"] == "forecast.calibration.v1" for event in events)
    assert all(event.metadata["subject_id"] == "AAPL" for event in events)
    assert all(event.metadata["sample_count"] == 25 for event in events)
```

- [ ] **Step 3: Run tests and verify adapter failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_quality_adapters.py -v`

Expected: FAIL because `quality_adapters.py` is missing.

- [ ] **Step 4: Implement adapters and collection hooks**

Scanner maps `mean`, `hit_rate`, `spread`, and `ic` for 1/5/10/20-day horizons. For each mean forward return, derive its 95% interval with `bootstrap_interval` from the corresponding non-null raw `TrackingRecord.fwd_*` samples; do not bootstrap the already-aggregated mean. Forecast maps direction accuracy, MAE, interval coverage, interval score skill, and mean interval width; rate observations include a Wilson interval derived from the reported sample count. Skip only absent or non-finite values; preserve zero.

Extend `register_scan_routes` with an optional `quality_sink: Callable[[list[AnalyticsEvent]], None] | None`. After `/scan/accuracy` builds its existing response, pass adapter events to that sink without altering the response. Register analytics before Scanner in `api_server.py` and pass a sink that loops over `_analytics_runtime.collector.submit`. After `/forecast/{market}/{code}/calibration` obtains either a cached or newly computed payload, submit Forecast events through the same runtime. When analytics is disabled, pass `None`. Catch and log adapter errors without payload content.

- [ ] **Step 5: Run focused domain and analytics tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_quality_adapters.py tests/scanner/test_scan_routes.py tests/test_forecast_robust_cache.py -v`

Expected: all tests PASS and existing route payloads remain unchanged.

- [ ] **Step 6: Commit Scanner/Forecast adapters**

```bash
git add agent/src/analytics/quality_adapters.py agent/src/api/scan_routes.py agent/api_server.py agent/tests/analytics
git commit -m "feat: track scanner and forecast quality"
```

### Task 3: Backtest and Paper Trading Quality Adapters

**Files:**
- Create: `agent/src/analytics/quality_identity.py`
- Modify: `agent/src/analytics/quality_adapters.py`
- Modify: `agent/backtest/run_card.py`
- Modify: `agent/src/paper_trading/models.py`
- Modify: `agent/src/paper_trading/storage.py`
- Create: `agent/tests/analytics/test_strategy_quality.py`
- Modify: `agent/tests/test_run_card.py`
- Modify: `agent/tests/test_paper_trading_storage.py`

**Interfaces:**
- Produces: `strategy_comparison_key(payload: Mapping[str, Any]) -> str | None`, `BacktestQualityAdapter.collect(runs_dir: Path) -> list[AnalyticsEvent]`, `PaperTradingQualityAdapter.collect(store: PaperTradingStore) -> list[AnalyticsEvent]`, `build_backtest_paper_gaps(backtests: list[StrategySeries], papers: list[StrategySeries]) -> list[AnalyticsEvent]`.
- Consumes: `agent/runs/*/run_card.json`, `PaperTradingStore.list_runs`, existing metric/formula versions.

- [ ] **Step 1: Write comparable-identity tests**

```python
def test_comparison_key_is_order_stable_and_rejects_incomplete_payload():
    left = {"market": "us", "holdings": [{"symbol": "MSFT", "weight": 0.4}, {"symbol": "AAPL", "weight": 0.6}], "strategy": {"name": "buy_and_hold", "params": {}}, "start_date": "2020-01-01", "end_date": "2025-01-01", "metric_version": "backtest.metrics.v2"}
    right = {**left, "holdings": list(reversed(left["holdings"]))}
    assert strategy_comparison_key(left) == strategy_comparison_key(right)
    assert strategy_comparison_key({"market": "us"}) is None
```

- [ ] **Step 2: Write adapter and gap tests**

```python
def test_matched_strategy_runs_emit_bootstrap_gap(tmp_path):
    key = "same-comparison-key"
    backtest = StrategySeries("back-1", key, {"total_return": 0.20, "sharpe": 1.1, "max_loss": -0.10, "max_drawdown": -0.12}, [("2026-07-01", 100), ("2026-07-02", 102), ("2026-07-03", 103)])
    paper = StrategySeries("paper-1", key, {"total_return": 0.15, "sharpe": 0.8, "max_loss": -0.12, "max_drawdown": -0.14}, [("2026-07-01", 100), ("2026-07-02", 101), ("2026-07-03", 101.5)])
    gaps = build_backtest_paper_gaps([backtest], [paper])
    by_metric = {event.metadata["metric_name"]: event for event in gaps}
    assert by_metric["paper_minus_backtest_return"].metadata["metric_value"] == -0.05
    assert by_metric["paper_minus_backtest_sharpe"].metadata["metric_value"] == -0.3
    assert by_metric["paired_daily_return_gap"].metadata["interval_low"] is not None
    different = StrategySeries("paper-2", "different", paper.metrics, paper.equity)
    assert build_backtest_paper_gaps([backtest], [different]) == []
```

- [ ] **Step 3: Run tests and verify failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_strategy_quality.py tests/test_run_card.py tests/test_paper_trading_storage.py -v`

Expected: FAIL on missing comparison identity and adapter methods.

- [ ] **Step 4: Implement explicit comparison identity**

Normalize market, sorted uppercase holdings with six-decimal weights, strategy name and sorted params, start/end dates, and metric version. Return SHA-256 canonical JSON. Add `comparison_key` to new run cards and `ExperimentMetadata`; preserve backward compatibility with `None` for existing files. Only compute gaps when both sides have an equal non-null key.

Backtest adapter scans `agent/runs/*/run_card.json`. Paper adapter uses `PaperTradingStore.list_runs(limit=500)` and completed runs only. Emit scalar metrics without recalculation. For a matched comparison key, load both equity curves, align by date, convert each to daily returns, and bootstrap the paired `paper_return - backtest_return` sample; if fewer than two aligned returns exist, emit a null gap with reason `insufficient_aligned_returns`. Deduplication uses run ID, metric, formula version, and updated/generated timestamp.

- [ ] **Step 5: Run strategy quality tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_strategy_quality.py tests/test_run_card.py tests/test_paper_trading_storage.py -v`

Expected: all tests PASS, including loading legacy metadata without `comparison_key`.

- [ ] **Step 6: Commit strategy adapters**

```bash
git add agent/src/analytics/quality_identity.py agent/src/analytics/quality_adapters.py agent/backtest/run_card.py agent/src/paper_trading/storage.py agent/src/paper_trading/models.py agent/tests/analytics/test_strategy_quality.py agent/tests/test_run_card.py agent/tests/test_paper_trading_storage.py
git commit -m "feat: track backtest and paper quality"
```

### Task 4: Research Rollups and API

**Files:**
- Modify: `agent/src/analytics/rollup.py`
- Modify: `agent/src/analytics/service.py`
- Modify: `agent/src/api/analytics_routes.py`
- Create: `agent/tests/analytics/test_research_api.py`

**Interfaces:**
- API: `GET /api/analytics/research-quality?days=30&subject=scanner&market=us&horizon=5d`.
- Produces: daily values, sample counts, Wilson/bootstrap intervals, baseline deltas, unavailable reasons.

- [ ] **Step 1: Write a failing API test with mixed sample sizes**

```python
def test_research_api_filters_and_reports_insufficient_samples(tmp_path):
    client, store = research_client(tmp_path)
    seed_quality(store, subject="scanner", market="us", horizon="5d", metric="hit_rate", value=0.57, sample_count=21)
    seed_quality(store, subject="forecast", market="us", horizon="63d", metric="directional_accuracy", value=0.55, sample_count=2)
    scanner = client.get("/api/analytics/research-quality?days=30&subject=scanner&market=us&horizon=5d").json()
    assert scanner["series"][0]["sample_count"] == 21
    assert scanner["series"][0]["interval_low"] is not None
    forecast = client.get("/api/analytics/research-quality?days=30&subject=forecast&market=us&horizon=63d").json()
    assert forecast["status"] == "insufficient_sample"
    assert forecast["value"] is None
```

- [ ] **Step 2: Run and verify failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_research_api.py -v`

Expected: FAIL because the research route is absent.

- [ ] **Step 3: Add research rollups and endpoint**

Aggregate by day, subject type, subject ID, market, horizon, regime, metric, and formula version. Preserve the source sample count; do not treat observations as independent rows when one observation already summarizes many samples. Rates require `sample_count >= 20`; other adapters may declare stricter minimums. Return comparison to the preceding equal-length window only when both windows pass the minimum.

- [ ] **Step 4: Run backend research tests and commit**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_research_api.py tests/analytics/test_rollup.py -v`

Expected: all tests PASS.

```bash
git add agent/src/analytics agent/src/api/analytics_routes.py agent/tests/analytics
git commit -m "feat: expose research quality trends"
```

### Task 5: Research Quality Frontend

**Files:**
- Create: `frontend/src/components/analytics/ResearchQualityView.tsx`
- Create: `frontend/src/components/analytics/__tests__/ResearchQualityView.test.tsx`
- Modify: `frontend/src/pages/Analytics.tsx`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: research-quality endpoint.
- Produces: “研究质量” view with subject, market, horizon, and regime filters.

- [ ] **Step 1: Write failing UI tests**

```typescript
it("shows uncertainty and never turns missing quality into zero", async () => {
  apiMock.getAnalyticsResearchQuality
    .mockResolvedValueOnce(scannerFixture({ value: 0.575, interval_low: 0.42, interval_high: 0.71, sample_count: 40 }))
    .mockResolvedValueOnce(Object.assign({}, forecastFixture, { status: "insufficient_sample", value: null }));
  render(<ResearchQualityView days={30} />);
  expect(await screen.findByText("57.5%")).toBeInTheDocument();
  expect(screen.getByText("n=40")).toBeInTheDocument();
  expect(screen.getByText(/42.0%.*71.0%/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Forecast" }));
  expect(await screen.findByText("样本不足")).toBeInTheDocument();
  expect(screen.queryByText("0%" )).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm run test:run -- src/components/analytics/__tests__/ResearchQualityView.test.tsx`

Expected: FAIL because the component and API method do not exist.

- [ ] **Step 3: Implement the research view**

Add typed `getAnalyticsResearchQuality` parameters. Render subject tabs for Scanner, Forecast, Backtest, and Paper Trading; render filters supported by the selected subject. Use `TrendChart` for absolute values and separate small charts for incompatible units. Tooltips show raw value, interval, sample count, formula version, and `data_through`.

- [ ] **Step 4: Run tests and full frontend build**

Run: `cd frontend && npm run test:run -- src/components/analytics/__tests__/ResearchQualityView.test.tsx src/pages/__tests__/Analytics.test.tsx && npm run build`

Expected: tests PASS and production build succeeds.

- [ ] **Step 5: Commit and verify Phase 2**

```bash
git add frontend/src/components/analytics frontend/src/pages/Analytics.tsx frontend/src/lib/api.ts
git commit -m "feat: add research quality dashboard"
```

Run: `cd agent && ../.venv/bin/pytest tests/analytics -v`

Expected: all analytics backend tests PASS.
