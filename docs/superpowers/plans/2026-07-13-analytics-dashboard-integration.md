# Analytics Dashboard Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate health scoring, explainable anomalies, trend-first overview, retention/privacy safeguards, and end-to-end acceptance into the completed analytics feature.

**Architecture:** A transparent rules engine turns already-aggregated metrics into dimension statuses, a composite score, and actionable anomaly records. The overview service joins usage, system, research, and development summaries; the React overview renders sparklines, one unit-safe trend explorer, anomaly cards, and release markers while preserving all drill-down views.

**Tech Stack:** Existing analytics modules and APIs, Python statistics, FastAPI, React 19, TypeScript, ECharts 6, pytest, Vitest.

## Global Constraints

- Execute after foundation, research-quality, and development-release plans.
- Overall health weights are product effectiveness 25%, system reliability 25%, data quality 20%, and research quality 30%.
- Metric statuses map to `healthy=100`, `watch=65`, `critical=25`; unavailable metrics are excluded.
- Overall score is unavailable when less than 50% of configured weight is observable.
- Label the score experimental until 30 calendar days of data exist.
- Candidate anomalies require at least seven historical days and robust `|z| >= 3.5`; they alert after two consecutive buckets unless a critical threshold fires.
- Different units never share a misleading default dual Y axis; standardized comparison is an explicit mode.
- Dashboard query fallback must label cached data stale with its generation time.
- Follow TDD and commit each reviewable task.

---

## File Structure

- `agent/src/analytics/health.py`: dimension status and composite score.
- `agent/src/analytics/anomalies.py`: candidate detection, persistence identity, ranking, action text.
- `agent/src/analytics/overview.py`: overview composition and last-success fallback.
- `frontend/src/components/analytics/TrendExplorer.tsx`: full trend, standardized mode, release marks.
- `frontend/src/components/analytics/OverviewView.tsx`: cards, anomalies, changes, development summary.
- `agent/tests/analytics/test_acceptance.py`: synthetic end-to-end requirements.

### Task 1: Transparent Health Scoring

**Files:**
- Create: `agent/src/analytics/health.py`
- Create: `agent/tests/analytics/test_health.py`

**Interfaces:**
- Produces: `MetricHealth`, `DimensionHealth`, `HealthSnapshot`, `classify_metric(metric: str, value: float | None, *, interval_low: float | None = None) -> MetricStatus | None`, `score_health(metrics: list[MetricHealth], history_days: int) -> HealthSnapshot`.
- Consumes: query-ready metric values/status rules; does not query SQLite directly.

- [ ] **Step 1: Write exact weighting and missing-data tests**

```python
import pytest

from src.analytics.health import MetricHealth, classify_metric, score_health


def test_health_score_uses_configured_dimension_weights():
    metrics = [
        MetricHealth("usage", "effective_session_rate", "healthy"),
        MetricHealth("system", "request_success_rate", "watch"),
        MetricHealth("data", "freshness_compliance", "healthy"),
        MetricHealth("research", "forecast_direction", "critical"),
    ]
    snapshot = score_health(metrics, history_days=30)
    assert snapshot.score == pytest.approx(68.75)
    assert snapshot.available_weight == 1.0
    assert snapshot.experimental is False


def test_health_score_excludes_missing_and_requires_half_weight():
    assert score_health([MetricHealth("research", "forecast_direction", "healthy")], history_days=10).score is None
    snapshot = score_health([
        MetricHealth("usage", "effective_session_rate", "healthy"),
        MetricHealth("system", "request_success_rate", "watch"),
    ], history_days=10)
    assert snapshot.score == pytest.approx(82.5)
    assert snapshot.experimental is True


def test_research_classification_uses_uncertainty():
    assert classify_metric("directional_accuracy", 0.56, interval_low=0.51) == "healthy"
    assert classify_metric("directional_accuracy", 0.56, interval_low=0.47) == "watch"
    assert classify_metric("directional_accuracy", 0.48, interval_low=0.40) == "critical"
```

- [ ] **Step 2: Run and verify failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_health.py -v`

Expected: FAIL because `health.py` is missing.

- [ ] **Step 3: Implement explicit rule inputs and score output**

Use these constants:

```python
DIMENSION_WEIGHTS = {"usage": 0.25, "system": 0.25, "data": 0.20, "research": 0.30}
STATUS_SCORES = {"healthy": 100.0, "watch": 65.0, "critical": 25.0}
```

Within a dimension, average available metric scores equally. Then renormalize available dimension weights. Return per-dimension score, contributing metric names/statuses, available weight, overall score, `experimental=history_days < 30`, and `calculation_version="health.v1"`. Development metrics are rejected as an unknown health dimension.

Implement these v1 classifications exactly:

```python
# metric: (healthy threshold, watch threshold); higher is better unless noted
HIGHER_IS_BETTER = {
    "result_view_rate": (0.70, 0.40),
    "effective_session_rate": (0.60, 0.30),
    "request_success_rate": (0.99, 0.95),
    "freshness_compliance_rate": (0.99, 0.95),
    "completeness_rate": (0.99, 0.95),
    "oos_sharpe": (1.00, 0.00),
}
LOWER_IS_BETTER = {
    "duration_p95_ratio_to_baseline": (1.25, 2.00),
    "absolute_paper_backtest_return_gap": (0.05, 0.15),
}
```

For `directional_accuracy`, return healthy only when the Wilson lower bound is greater than `0.50`, watch when the point estimate is at least `0.50`, otherwise critical. For `top_bottom_spread_pct`, return healthy only when the interval lower bound is positive, watch when the point estimate is positive, otherwise critical. An unknown or unavailable metric produces no `MetricHealth` and must not silently receive a status.

- [ ] **Step 4: Run and commit**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_health.py -v`

Expected: all tests PASS.

```bash
git add agent/src/analytics/health.py agent/tests/analytics/test_health.py
git commit -m "feat: add transparent analytics health score"
```

### Task 2: Explainable Anomaly Engine

**Files:**
- Create: `agent/src/analytics/anomalies.py`
- Create: `agent/tests/analytics/test_anomalies.py`

**Interfaces:**
- Produces: `detect_anomalies(series, rule) -> list[AnalyticsAnomaly]`, `rank_anomalies(items)`.
- Consumes: Phase 1 `robust_z_score`, metric points, rule configuration.

- [ ] **Step 1: Write synthetic trend tests**

```python
from src.analytics.anomalies import AnomalyRule, detect_anomalies


def test_two_consecutive_outliers_create_one_actionable_anomaly():
    baseline = [98.0, 101.0, 99.0, 102.0, 100.0, 97.0, 101.0]
    series = [(f"2026-07-{day:02d}", value) for day, value in enumerate(baseline, start=1)] + [("2026-07-08", 180.0), ("2026-07-09", 190.0)]
    items = detect_anomalies(series, AnomalyRule(metric="duration_p95_ms", direction="high", minimum_sample=20, action="查看慢请求"), sample_counts=[50] * 9)
    assert len(items) == 1
    assert items[0].first_bucket == "2026-07-08"
    assert items[0].latest_bucket == "2026-07-09"
    assert items[0].action == "查看慢请求"


def test_noise_and_small_samples_do_not_alert():
    series = [(f"2026-07-{day:02d}", value) for day, value in enumerate([99, 101, 98, 102, 100, 101, 99, 103, 98], start=1)]
    rule = AnomalyRule(metric="duration_p95_ms", direction="high", minimum_sample=20, action="查看慢请求")
    assert detect_anomalies(series, rule, sample_counts=[100] * 9) == []
    assert detect_anomalies(series[:-1] + [("2026-07-09", 500)], rule, sample_counts=[100] * 8 + [2]) == []
```

- [ ] **Step 2: Run and verify failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_anomalies.py -v`

Expected: FAIL because `anomalies.py` is missing.

- [ ] **Step 3: Implement rule semantics and ranking**

Rules include metric, direction, minimum sample, optional critical threshold, domain, severity label, and action. Use only preceding values as the baseline. `high` requires positive robust Z; `low` requires negative robust Z. Critical thresholds alert immediately. Identity is SHA-256 of domain, metric, dimensions, and first bucket. Rank by severity (`critical`, `warning`, `info`), then consecutive bucket count, impacted sample count, and latest bucket descending.

Add a separate absence rule for the known feature registry `{overview, scanner, forecast, paper_trading, news_center, research_analysis}`. If the collector has product events on at least 7 of the last 14 days but a known feature has zero page views across all 14 days, emit an info anomaly with action `检查入口或隐藏功能`; if overall product coverage is insufficient, emit no absence conclusion.

Add initial rules:

```python
DEFAULT_RULES = (
    AnomalyRule("request_success_rate", "low", 20, 0.95, "system", "critical", "查看失败接口"),
    AnomalyRule("duration_p95_ms", "high", 20, None, "system", "warning", "查看慢请求"),
    AnomalyRule("result_view_rate", "low", 20, None, "usage", "warning", "查看用户路径"),
    AnomalyRule("directional_accuracy", "low", 20, 0.50, "research", "critical", "按市场状态检查模型"),
    AnomalyRule("data_freshness_p95_ms", "high", 20, None, "data", "warning", "查看数据源"),
)
```

- [ ] **Step 4: Run and commit**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_anomalies.py tests/analytics/test_statistics.py -v`

Expected: all tests PASS.

```bash
git add agent/src/analytics/anomalies.py agent/tests/analytics/test_anomalies.py
git commit -m "feat: detect explainable analytics anomalies"
```

### Task 3: Overview Service, API, and Stale Fallback

**Files:**
- Create: `agent/src/analytics/overview.py`
- Create: `agent/tests/analytics/test_overview.py`
- Modify: `agent/src/analytics/store.py`
- Modify: `agent/src/analytics/service.py`
- Modify: `agent/src/api/analytics_routes.py`

**Interfaces:**
- Produces: `AnalyticsOverviewService.build(days, compare=True)`, `GET /api/analytics/overview`.
- Consumes: health, anomalies, trends, development summary, and stored last-success overview snapshot.

- [ ] **Step 1: Write overview composition tests**

```python
def test_overview_composes_all_available_domains(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    seed_overview_points(store, days=30, include_research=False)
    service = AnalyticsOverviewService(store, development=fake_development_summary())
    result = service.build(days=30, compare=True)
    assert [card.metric for card in result.cards] == ["health_score", "effective_research_sessions", "task_success_rate", "directional_accuracy"]
    assert result.cards[-1].value is None
    assert result.cards[-1].reason == "no_research_data"
    assert [item.severity for item in result.anomalies] == sorted([item.severity for item in result.anomalies], key={"critical": 0, "warning": 1, "info": 2}.get)
    assert result.development.latest_features
    assert result.calculation_version == "overview.v1"
```

- [ ] **Step 2: Write stale fallback test**

```python
def test_overview_returns_last_success_with_stale_warning(tmp_path, monkeypatch):
    store = AnalyticsStore(tmp_path / "a.db")
    seed_overview_points(store, days=30)
    service = AnalyticsOverviewService(store, development=fake_development_summary())
    fresh = service.build(days=30, compare=True)
    monkeypatch.setattr(store, "query_metric_points", lambda **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    stale = service.build(days=30, compare=True)
    assert stale.generated_at == fresh.generated_at
    assert stale.warnings == ["analytics_query_failed", "stale_snapshot"]
```

- [ ] **Step 3: Run and verify failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_overview.py -v`

Expected: FAIL because overview service and snapshot storage are absent.

- [ ] **Step 4: Implement composition and snapshot storage**

Add `overview_snapshots` keyed by days, compare flag, and calculation version. Save canonical response JSON only after a successful build. `build` queries the selected window and the immediately preceding equal window, derives comparison deltas using summed ratio inputs or sample-weighted scalar means, and persists the response. Catch only storage/query errors for fallback; validation/programming errors must surface in tests.

- [ ] **Step 5: Add authenticated route and run tests**

`GET /api/analytics/overview?days=30&compare=true` sets `Cache-Control: no-store` and returns the service payload.

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_overview.py tests/analytics/test_routes.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit overview backend**

```bash
git add agent/src/analytics agent/src/api/analytics_routes.py agent/tests/analytics
git commit -m "feat: compose analytics overview"
```

### Task 4: Trend Explorer with Release Markers

**Files:**
- Create: `frontend/src/components/analytics/TrendExplorer.tsx`
- Create: `frontend/src/components/analytics/__tests__/TrendExplorer.test.tsx`
- Modify: `frontend/src/lib/echarts.ts`

**Interfaces:**
- Produces: `TrendExplorer` modes `absolute | standardized | change`.
- Consumes: metric series with unit, baseline, interval, sample count, and release markers.

- [ ] **Step 1: Write chart option tests**

Extract `buildTrendExplorerOption(input, theme)` as a pure function and add:

```typescript
it("separates units and adds release provenance", () => {
  const option = buildTrendExplorerOption(trendFixture, themeFixture, "absolute");
  expect(option.grid).toHaveLength(2);
  expect(option.xAxis).toHaveLength(2);
  expect(JSON.stringify(option)).toContain("v0.1.9");
  expect(JSON.stringify(option)).toContain("n=40");
});

it("standardizes compatible series onto one grid", () => {
  const option = buildTrendExplorerOption(trendFixture, themeFixture, "standardized");
  expect(option.grid).toHaveLength(1);
  const values = option.series[0].data as number[];
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  expect(mean).toBeCloseTo(0, 10);
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm run test:run -- src/components/analytics/__tests__/TrendExplorer.test.tsx`

Expected: FAIL because `TrendExplorer.tsx` is missing.

- [ ] **Step 3: Implement the pure option builder and component lifecycle**

Do not standardize a series with fewer than three finite points or zero standard deviation; mark it unavailable. Use ECharts `markLine` for releases and `markArea`/stacked invisible lower bound for intervals. Reuse the existing dark theme, `ResizeObserver`, and chart disposal patterns. Expose accessible buttons for domain and mode selection outside the canvas.

- [ ] **Step 4: Run chart tests and commit**

Run: `cd frontend && npm run test:run -- src/components/analytics/__tests__/TrendExplorer.test.tsx`

Expected: all tests PASS.

```bash
git add frontend/src/components/analytics/TrendExplorer.tsx frontend/src/components/analytics/__tests__/TrendExplorer.test.tsx frontend/src/lib/echarts.ts
git commit -m "feat: add analytics trend explorer"
```

### Task 5: Trend-First Overview UI

**Files:**
- Create: `frontend/src/components/analytics/OverviewView.tsx`
- Create: `frontend/src/components/analytics/__tests__/OverviewView.test.tsx`
- Modify: `frontend/src/pages/Analytics.tsx`
- Modify: `frontend/src/pages/__tests__/Analytics.test.tsx`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: overview endpoint and existing four drill-down views.
- Produces: final five-view dashboard: 总览、功能使用、系统健康、研究质量、研发与版本.

- [ ] **Step 1: Write failing overview behavior tests**

```typescript
it("renders trend-first overview and honest unavailable state", async () => {
  apiMock.getAnalyticsOverview.mockResolvedValueOnce(overviewFixture({ health: 78, experimental: true }));
  render(<Analytics />);
  expect(await screen.findByText("78")).toBeInTheDocument();
  expect(screen.getByText("实验性")).toBeInTheDocument();
  expect(screen.getAllByTestId("metric-sparkline")).toHaveLength(4);
  expect(screen.getByRole("button", { name: "30 天" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("v0.1.9")).toBeInTheDocument();

  apiMock.getAnalyticsOverview.mockResolvedValueOnce(overviewFixture({ health: null, warnings: ["stale_snapshot"] }));
  await userEvent.click(screen.getByRole("button", { name: "7 天" }));
  expect(await screen.findByText("数据不足")).toBeInTheDocument();
  expect(screen.getByText(/最后更新/)).toBeInTheDocument();
  expect(screen.queryByText("0")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm run test:run -- src/components/analytics/__tests__/OverviewView.test.tsx src/pages/__tests__/Analytics.test.tsx`

Expected: FAIL because OverviewView and overview API method are absent.

- [ ] **Step 3: Implement final information architecture**

Add `getAnalyticsOverview(days, compare)`. Render top cards, `TrendExplorer`, anomaly/action list, weekly changes, and development summary. Maintain filter state in URL query parameters `view`, `days`, and `compare` so reload/back navigation preserves context. Use cards and grid breakpoints consistent with existing pages; on narrow screens stack charts and anomaly cards without horizontal page scrolling.

- [ ] **Step 4: Run UI tests, complete frontend suite, and build**

Run: `cd frontend && npm run test:run`

Expected: entire Vitest suite PASS.

Run: `cd frontend && npm run build`

Expected: TypeScript and Vite production build PASS.

- [ ] **Step 5: Commit final dashboard UI**

```bash
git add frontend/src/components/analytics frontend/src/pages/Analytics.tsx frontend/src/pages/__tests__/Analytics.test.tsx frontend/src/lib/api.ts
git commit -m "feat: complete trend-first analytics dashboard"
```

### Task 6: Retention, Privacy, Performance, and Acceptance

**Files:**
- Modify: `agent/src/analytics/store.py`
- Modify: `agent/src/analytics/runtime.py`
- Create: `agent/tests/analytics/test_retention_privacy.py`
- Create: `agent/tests/analytics/test_performance.py`
- Create: `agent/tests/analytics/test_acceptance.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `AnalyticsStore.apply_retention(now)`, acceptance evidence for the full design.
- Consumes: all prior analytics components.

- [ ] **Step 1: Write retention and sensitive-data tests**

```python
def test_retention_deletes_only_expired_short_lived_rows(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    seed_retention_rows(store, product_days=[91, 89], system_days=[91, 89], quality_days=[365], development_days=[365], hourly_days=[181, 179], daily_days=[365])
    deleted = store.apply_retention(datetime(2026, 7, 13, tzinfo=timezone.utc))
    assert deleted == {"raw_events": 2, "hourly_points": 1}
    assert event_ages(store, "product") == [89]
    assert event_ages(store, "quality") == [365]
    assert metric_ages(store, "day") == [365]


def test_store_and_logs_never_contain_sensitive_values(tmp_path, caplog):
    store = AnalyticsStore(tmp_path / "a.db")
    collector = AnalyticsCollector(store)
    secret = "seeded-super-secret"
    collector.submit(product_event(metadata={"prompt": secret}))
    serialized = dump_all_analytics_rows(store) + caplog.text
    for forbidden in ["api_key", "authorization", "prompt", "response", "token", secret]:
        assert forbidden.lower() not in serialized.lower()
```

- [ ] **Step 2: Write performance budget tests**

```python
@pytest.mark.performance
def test_overview_query_and_middleware_budget(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    seed_large_dataset(store, raw_events=100_000, aggregate_days=365)
    service = AnalyticsOverviewService(store, development=fake_development_summary())
    service.build(30, True)
    durations = [timed_ms(lambda: service.build(30, True)) for _ in range(5)]
    assert statistics.median(durations) < 500
    disabled = benchmark_noop_requests(analytics_enabled=False, requests=1_000)
    enabled = benchmark_noop_requests(analytics_enabled=True, requests=1_000)
    assert percentile(enabled, 95) <= percentile(disabled, 95) * 1.05
```

Mark the test with `@pytest.mark.performance` and keep it out of default CI if host noise makes it unstable; run it explicitly for release acceptance.

- [ ] **Step 3: Write synthetic end-to-end acceptance tests**

```python
def test_four_domains_and_two_anomaly_types_end_to_end(tmp_path):
    app, store = analytics_test_app(tmp_path)
    seed_four_domains(store, days=7)
    seed_anomaly_tail(store, metric="duration_p95_ms", baseline=[98, 101, 99, 102, 100, 97, 101], tail=[180, 190])
    seed_anomaly_tail(store, metric="directional_accuracy", baseline=[0.58, 0.57, 0.59, 0.56, 0.58, 0.57, 0.58], tail=[0.48, 0.47])
    payload = TestClient(app).get("/api/analytics/overview?days=30").json()
    assert {group["domain"] for group in payload["trend_groups"]} == {"usage", "system", "research", "development"}
    assert {item["domain"] for item in payload["anomalies"]} >= {"system", "research"}


def test_disabling_analytics_preserves_scanner_response(tmp_path, monkeypatch):
    enabled = build_full_app(tmp_path, analytics_enabled=True)
    disabled = build_full_app(tmp_path, analytics_enabled=False)
    monkeypatch.setattr("src.api.scan_routes.load_latest", lambda **kwargs: fixed_scan_result())
    assert TestClient(enabled).get("/scan/latest").json() == TestClient(disabled).get("/scan/latest").json()
```

- [ ] **Step 4: Run tests and verify failures**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_retention_privacy.py tests/analytics/test_acceptance.py -v`

Expected: FAIL until retention and final integration behavior are implemented.

- [ ] **Step 5: Implement bounded daily retention**

Delete in batches of 5,000 rows after the previous day's rollup, using UTC cutoffs for events and local bucket dates for aggregates. Repeat until a batch deletes fewer than 5,000 rows, yielding between batches in the runtime. Never run retention in a request handler. Record only deleted row counts.

- [ ] **Step 6: Document local analytics behavior**

Add a README section with `/analytics`, the four data domains, local `analytics.db` path, `ANALYTICS_ENABLED=0` opt-out, retention periods, privacy exclusions, and the correlation disclaimer. State that this is research observability, not investment advice.

- [ ] **Step 7: Run full verification**

Run: `cd agent && ../.venv/bin/pytest tests/analytics -v`

Expected: all analytics tests PASS.

Run: `cd agent && ../.venv/bin/pytest`

Expected: complete backend suite PASS.

Run: `cd frontend && npm run test:run && npm run build`

Expected: complete frontend suite and production build PASS.

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_performance.py -m performance -v`

Expected: overview median below 500 ms and middleware P95 regression no more than 5%.

- [ ] **Step 8: Commit release acceptance work**

```bash
git add agent/src/analytics agent/tests/analytics README.md
git commit -m "test: verify analytics privacy and performance"
```

- [ ] **Step 9: Inspect the final branch**

Run: `git status --short`

Expected: clean worktree.

Run: `git log --oneline --decorate -12`

Expected: frequent commits covering store, collector, rollups, routes, instrumentation, research quality, development intelligence, health/anomalies, UI, and acceptance.
