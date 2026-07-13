# Analytics Foundation, Usage, and System Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local analytics event pipeline and ship a working `/analytics` page with product-usage and system-health trends.

**Architecture:** A bounded best-effort collector writes allowlisted events to an independent WAL-mode SQLite database under the runtime root. An idempotent hourly/daily rollup produces query-ready metrics, FastAPI exposes authenticated analytics endpoints, and the React page renders the first two dashboard views without recomputing metrics in the browser.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, stdlib `sqlite3`/`asyncio`, React 19, TypeScript 5, ECharts 6, Vitest, pytest.

## Global Constraints

- Store analytics in `<runtime-root>/analytics.db`; never mix it into a business database.
- `ANALYTICS_ENABLED` defaults to enabled locally and sends no analytics data over an external network.
- Collection is best-effort: queue, validation, or database failures must not change a business response.
- Reject unknown metadata keys and never persist prompts, responses, credentials, request bodies, or tokens.
- Raw product/system events retain 90 days; hourly aggregates retain 180 days; daily aggregates retain indefinitely.
- Unavailable metrics are `null` with a reason code, never fabricated zeroes.
- Follow TDD and commit after every independently reviewable task.

---

## File Structure

- `agent/src/analytics/models.py`: shared event and metric contracts.
- `agent/src/analytics/store.py`: SQLite schema, transactions, event dedupe, aggregates, retention.
- `agent/src/analytics/collector.py`: metadata allowlist and bounded non-blocking queue.
- `agent/src/analytics/statistics.py`: EWMA, moving median, Wilson interval, robust Z-score.
- `agent/src/analytics/rollup.py`: idempotent hourly/daily usage and system aggregation.
- `agent/src/analytics/service.py`: query orchestration and response models.
- `agent/src/analytics/runtime.py`: collector flush loop and rollup scheduler lifecycle.
- `agent/src/api/analytics_routes.py`: `/api/analytics` routes.
- `frontend/src/lib/analytics.ts`: product-event batching and local anonymous identity.
- `frontend/src/components/analytics/TrendChart.tsx`: shared absolute-value trend chart.
- `frontend/src/pages/Analytics.tsx`: usage/system page shell.

### Task 1: Event Contracts and SQLite Store

**Files:**
- Create: `agent/src/analytics/__init__.py`
- Create: `agent/src/analytics/models.py`
- Create: `agent/src/analytics/store.py`
- Create: `agent/tests/analytics/__init__.py`
- Create: `agent/tests/analytics/test_store.py`

**Interfaces:**
- Produces: `AnalyticsEvent`, `EventBatch`, `MetricPoint`, `AnalyticsStore.append_events(events: list[AnalyticsEvent]) -> int`, `AnalyticsStore.query_events(*, kind: str | None = None, start: datetime | None = None, end: datetime | None = None) -> list[AnalyticsEvent]`, `AnalyticsStore.upsert_metric_points(points: list[MetricPoint]) -> None`.
- Consumes: `src.config.paths.get_runtime_root()` for the default database path.

- [ ] **Step 1: Write failing store tests**

```python
from datetime import datetime, timezone

from src.analytics.models import AnalyticsEvent, MetricPoint
from src.analytics.store import AnalyticsStore


def _event(event_id: str = "evt-1") -> AnalyticsEvent:
    return AnalyticsEvent(
        event_id=event_id,
        kind="product",
        occurred_at=datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc),
        workspace_id="local",
        user_id="user-hash",
        feature="scanner",
        action="result_view",
        outcome="success",
        duration_ms=120,
        metadata={"route": "/scanner"},
    )


def test_append_deduplicates_event_id(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    assert store.append_events([_event()]) == 1
    assert store.append_events([_event()]) == 0
    assert [row.event_id for row in store.query_events(kind="product")] == ["evt-1"]


def test_metric_point_preserves_sample_and_interval(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    point = MetricPoint(
        bucket="2026-07-13", granularity="day", domain="usage",
        metric="result_view_rate", dimensions={"feature": "scanner"},
        value=0.75, numerator=3, denominator=4, sample_count=4,
        interval_low=0.30, interval_high=0.95,
        calculation_version="analytics.v1",
    )
    store.upsert_metric_points([point])
    assert store.query_metric_points(metric="result_view_rate")[0] == point
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_store.py -v`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'src.analytics'`.

- [ ] **Step 3: Add concrete Pydantic contracts and schema-v1 storage**

Implement these exact public models in `models.py`:

```python
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalyticsEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    kind: Literal["product", "system", "quality", "development"]
    occurred_at: datetime
    workspace_id: str = "local"
    user_id: str = "local"
    session_id: str | None = None
    feature: str
    action: str
    outcome: Literal["success", "failure", "cancelled", "unknown"] = "unknown"
    duration_ms: int | None = Field(default=None, ge=0)
    app_version: str | None = None
    commit_sha: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventBatch(BaseModel):
    events: list[AnalyticsEvent] = Field(min_length=1, max_length=100)


class MetricPoint(BaseModel):
    bucket: str
    granularity: Literal["hour", "day", "release"]
    domain: Literal["usage", "system", "data", "research", "development", "health"]
    metric: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    value: float | None
    numerator: float | None = None
    denominator: float | None = None
    sample_count: int = Field(ge=0)
    interval_low: float | None = None
    interval_high: float | None = None
    calculation_version: str
```

In `store.py`, create `raw_events` with `event_id TEXT PRIMARY KEY`, UTC timestamp, normalized columns, and `metadata_json`; create `metric_points` with a primary key over bucket, granularity, domain, metric, canonical dimensions JSON, and calculation version. Use `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA user_version=1`, context-managed connections, `INSERT OR IGNORE` for events, and `ON CONFLICT DO UPDATE` for points. Serialize dimensions with `json.dumps(value, sort_keys=True, separators=(",", ":"))`.

- [ ] **Step 4: Run store tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_store.py -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Commit the storage boundary**

```bash
git add agent/src/analytics agent/tests/analytics
git commit -m "feat: add analytics event store"
```

### Task 2: Allowlisted Best-Effort Collector

**Files:**
- Create: `agent/src/analytics/collector.py`
- Create: `agent/tests/analytics/test_collector.py`

**Interfaces:**
- Consumes: `AnalyticsEvent`, `AnalyticsStore.append_events`.
- Produces: `AnalyticsCollector.submit(event) -> bool`, `flush(limit=100) -> int`, `dropped_count`, `rejected_count`.

- [ ] **Step 1: Write failing queue and privacy tests**

```python
from src.analytics.collector import AnalyticsCollector
from src.analytics.store import AnalyticsStore
from tests.analytics.test_store import _event


def test_full_queue_drops_without_raising(tmp_path):
    collector = AnalyticsCollector(AnalyticsStore(tmp_path / "a.db"), max_queue=1)
    assert collector.submit(_event("one")) is True
    assert collector.submit(_event("two")) is False
    assert collector.dropped_count == 1


def test_unknown_or_sensitive_metadata_is_rejected(tmp_path):
    collector = AnalyticsCollector(AnalyticsStore(tmp_path / "a.db"))
    assert collector.submit(_event().model_copy(update={"metadata": {"prompt": "secret"}})) is False
    assert collector.rejected_count == 1


def test_flush_persists_valid_events(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    collector = AnalyticsCollector(store)
    collector.submit(_event("one"))
    collector.submit(_event("two"))
    assert collector.flush() == 2
    assert len(store.query_events(kind="product")) == 2
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_collector.py -v`

Expected: FAIL because `src.analytics.collector` does not exist.

- [ ] **Step 3: Implement the bounded collector**

Use `queue.Queue(maxsize=max_queue)` and `put_nowait`. Define allowlists exactly as:

```python
ALLOWED_METADATA = {
    "product": {"route", "market", "result_count", "source"},
    "system": {"route", "method", "provider", "market", "status_code", "error_code", "data_freshness_ms", "freshness_slo_ms", "expected_count", "observed_count"},
    "quality": {"subject_type", "subject_id", "market", "horizon", "regime", "metric_name", "metric_value", "sample_count", "interval_low", "interval_high", "formula_version", "as_of", "reason"},
    "development": {"version", "summary", "files_changed", "insertions", "deletions", "modules", "test_files_changed"},
}
FORBIDDEN_KEYS = {"prompt", "response", "api_key", "token", "authorization", "request_body", "credential"}
```

Reject an event when a metadata key is forbidden or absent from its kind allowlist. `flush` drains at most `limit` items, calls `append_events` once, and returns the inserted count; on `sqlite3.Error`, restore no items, increment `dropped_count` by the drained batch size, log only the count and exception class, and return zero.

- [ ] **Step 4: Run collector tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_collector.py -v`

Expected: 3 tests PASS.

- [ ] **Step 5: Commit collector behavior**

```bash
git add agent/src/analytics/collector.py agent/tests/analytics/test_collector.py
git commit -m "feat: add privacy-safe analytics collector"
```

### Task 3: Statistics and Idempotent Usage/System Rollups

**Files:**
- Create: `agent/src/analytics/statistics.py`
- Create: `agent/src/analytics/rollup.py`
- Create: `agent/tests/analytics/test_statistics.py`
- Create: `agent/tests/analytics/test_rollup.py`

**Interfaces:**
- Produces: `ewma(values, alpha=0.3)`, `moving_median(values, window=7)`, `wilson_interval(successes, total)`, `robust_z_score(value, history)`, `AnalyticsRollup.run_day(day) -> list[MetricPoint]`.
- Consumes: raw event queries and `AnalyticsStore.upsert_metric_points`.

- [ ] **Step 1: Write exact statistical tests**

```python
import pytest

from src.analytics.statistics import ewma, moving_median, robust_z_score, wilson_interval


def test_ewma_and_median_are_deterministic():
    assert ewma([10.0, 20.0, 20.0], alpha=0.3) == pytest.approx([10.0, 13.0, 15.1])
    assert moving_median([1.0, 100.0, 2.0], window=3) == [1.0, 50.5, 2.0]


def test_wilson_and_robust_z_handle_small_or_flat_samples():
    low, high = wilson_interval(15, 20)
    assert (low, high) == pytest.approx((0.5313, 0.8881), abs=1e-4)
    assert robust_z_score(9.0, [1, 2, 2, 2, 3, 2, 1]) > 3.5
    assert robust_z_score(2.0, [2, 2, 2, 2, 2, 2, 2]) == 0.0
```

- [ ] **Step 2: Write a failing daily rollup test**

```python
from datetime import date

from src.analytics.rollup import AnalyticsRollup
from src.analytics.store import AnalyticsStore
from tests.analytics.test_store import _event


def test_daily_rollup_is_idempotent_and_keeps_fraction_inputs(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    events = [
        _event("a"),
        _event("b").model_copy(update={"action": "task_start"}),
        _event("c").model_copy(update={"action": "task_complete"}),
        _event("d").model_copy(update={"action": "task_complete", "outcome": "failure"}),
    ]
    store.append_events(events)
    rollup = AnalyticsRollup(store)
    rollup.run_day(date(2026, 7, 13))
    rollup.run_day(date(2026, 7, 13))
    points = store.query_metric_points(metric="task_success_rate")
    assert len(points) == 1
    assert (points[0].numerator, points[0].denominator, points[0].value) == (1, 2, 0.5)
```

- [ ] **Step 3: Run tests and verify missing implementations**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_statistics.py tests/analytics/test_rollup.py -v`

Expected: FAIL on missing `statistics` and `rollup` modules.

- [ ] **Step 4: Implement formulas and v1 rollup metrics**

Implement formulas with stdlib `math` and `statistics`; Wilson uses `z=1.959963984540054`. `robust_z_score` returns `0.0` when fewer than 7 history values or MAD is zero. `AnalyticsRollup.run_day` creates these day metrics per feature/route where applicable:

```python
USAGE_METRICS = (
    "page_views", "task_starts", "task_completions", "task_success_rate",
    "result_views", "result_view_rate", "research_sessions",
    "effective_research_sessions", "effective_session_rate",
    "time_to_insight_p50_ms", "time_to_insight_p95_ms",
)
SYSTEM_METRICS = (
    "request_count", "request_success_rate", "duration_p50_ms", "duration_p95_ms",
    "timeout_count", "data_freshness_p95_ms",
)
DATA_METRICS = (
    "freshness_compliance_rate", "completeness_rate",
)
```

An effective session requires one successful `task_complete` and a later `result_view` in the same non-null session. `research_sessions` counts distinct sessions with `task_start`; `effective_session_rate` divides effective sessions by research sessions. Freshness compliance counts observations where `data_freshness_ms <= freshness_slo_ms`; completeness sums `observed_count / expected_count` only when the expected count is positive. A ratio point stores numerator, denominator, sample count, and Wilson interval. Percentiles use nearest-rank with a sorted list. Call `upsert_metric_points` once at the end.

- [ ] **Step 5: Run rollup tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_statistics.py tests/analytics/test_rollup.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit statistical aggregation**

```bash
git add agent/src/analytics/statistics.py agent/src/analytics/rollup.py agent/tests/analytics
git commit -m "feat: aggregate analytics usage and system trends"
```

### Task 4: Runtime, HTTP Observation, and FastAPI Routes

**Files:**
- Create: `agent/src/analytics/runtime.py`
- Create: `agent/src/analytics/service.py`
- Create: `agent/src/api/analytics_routes.py`
- Create: `agent/tests/analytics/test_routes.py`
- Create: `agent/tests/analytics/test_runtime.py`
- Modify: `agent/api_server.py`
- Create: `agent/tests/analytics/test_provider_observation.py`

**Interfaces:**
- Produces: `AnalyticsRuntime.start() -> None`, `stop() -> None`, `observe_http(request: Request, status_code: int, duration_ms: int) -> None`, `register_analytics_routes(app: FastAPI, *, require_auth: AuthDep, service: AnalyticsService) -> None`.
- API: `POST /api/analytics/events`, `GET /api/analytics/trends`, `GET /api/analytics/usage`, `GET /api/analytics/system-health`.

- [ ] **Step 1: Write route authentication and contract tests**

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.analytics.collector import AnalyticsCollector
from src.analytics.rollup import AnalyticsRollup
from src.analytics.service import AnalyticsService
from src.analytics.store import AnalyticsStore
from src.api.analytics_routes import register_analytics_routes


def _client(tmp_path):
    app = FastAPI()
    store = AnalyticsStore(tmp_path / "a.db")
    service = AnalyticsService(store, AnalyticsCollector(store), AnalyticsRollup(store))
    register_analytics_routes(app, require_auth=lambda: None, service=service)
    return TestClient(app), store


def test_event_batch_and_empty_trend_contract(tmp_path):
    client, store = _client(tmp_path)
    payload = {"events": [{
        "event_id": "web-1", "kind": "product", "occurred_at": "2026-07-13T09:00:00Z",
        "workspace_id": "local", "user_id": "u", "feature": "scanner",
        "action": "page_view", "outcome": "success", "metadata": {"route": "/scanner"},
    }]}
    assert client.post("/api/analytics/events", json=payload).status_code == 202
    assert len(store.query_events(kind="product")) == 0
    response = client.get("/api/analytics/trends?metric=page_views&days=30")
    assert response.status_code == 200
    assert response.json()["points"] == []
    assert response.json()["warnings"] == ["no_data"]
```

- [ ] **Step 2: Write runtime failure-isolation tests**

```python
import asyncio
import sqlite3

import pytest

from src.analytics.collector import AnalyticsCollector
from src.analytics.rollup import AnalyticsRollup
from src.analytics.runtime import AnalyticsRuntime
from src.analytics.store import AnalyticsStore
from tests.analytics.test_store import _event


class FailingStore(AnalyticsStore):
    def append_events(self, events):
        raise sqlite3.OperationalError("locked")


@pytest.mark.asyncio
async def test_runtime_isolates_flush_failure(tmp_path):
    store = FailingStore(tmp_path / "a.db")
    collector = AnalyticsCollector(store)
    collector.submit(_event())
    runtime = AnalyticsRuntime(collector, AnalyticsRollup(store), poll_seconds=0.01)
    assert await runtime.flush_once() == 0


@pytest.mark.asyncio
async def test_runtime_stops_cleanly(tmp_path):
    store = AnalyticsStore(tmp_path / "a.db")
    runtime = AnalyticsRuntime(AnalyticsCollector(store), AnalyticsRollup(store), poll_seconds=0.01)
    runtime.start()
    await asyncio.sleep(0.02)
    await runtime.stop()
    assert runtime.task is None
```

- [ ] **Step 3: Run tests and verify missing modules**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_routes.py tests/analytics/test_runtime.py -v`

Expected: FAIL on missing service/runtime/routes.

- [ ] **Step 4: Implement runtime and routes**

`AnalyticsRuntime` owns one async task. Every second it calls `collector.flush(100)` via `asyncio.to_thread`; every hour it calls the rollup catch-up for missing days. `stop` cancels the loop and performs one bounded final flush.

Add `AnalyticsRuntime.observe_provider(provider, market, status, duration_ms, observed_count, expected_count, data_freshness_ms, freshness_slo_ms)`. In `api_server._fetch_price_history`, time each resolved-loader call and report the loader module name, market, success/failure, one expected symbol, whether a non-empty frame was observed, age of the newest bar, and a freshness SLO of one hour for intraday or 72 hours for daily history. A provider observer exception is swallowed. Add a test with a fake loader and fake runtime proving one success and one failure observation while the original return/exception behavior stays unchanged.

The event route validates `EventBatch`, calls `collector.submit` for each item, and returns HTTP 202 with `{accepted, rejected, dropped}`. Query endpoints accept `days: Literal[7, 30, 90]`, return `data_through`, `generated_at`, `sample_count`, `calculation_version="analytics.v1"`, `warnings`, and points.

In `api_server.py`, register the analytics runtime before the Scanner route registration so later domain routes can receive its collector. Add the middleware:

```python
_analytics_runtime = None


@app.middleware("http")
async def _observe_http_analytics(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        if _analytics_runtime is not None:
            _analytics_runtime.observe_http(request, status_code=500, duration_ms=int((time.perf_counter() - started) * 1000))
        raise
    if _analytics_runtime is not None:
        _analytics_runtime.observe_http(request, status_code=response.status_code, duration_ms=int((time.perf_counter() - started) * 1000))
    return response
```

Exclude `/api/analytics/events`, static assets, and `/health` from HTTP observation. Register routes with `require_local_or_auth`. Start and stop the runtime in the existing startup/shutdown handlers only when `ANALYTICS_ENABLED` is not one of `0,false,no,off`.

- [ ] **Step 5: Run route/runtime tests and focused API smoke tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_routes.py tests/analytics/test_runtime.py tests/test_settings_api.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit the backend vertical slice**

```bash
git add agent/src/analytics agent/src/api/analytics_routes.py agent/api_server.py agent/tests/analytics
git commit -m "feat: expose local analytics APIs"
```

### Task 5: Browser Event Transport and Core Feature Instrumentation

**Files:**
- Create: `frontend/src/lib/analytics.ts`
- Create: `frontend/src/lib/__tests__/analytics.test.ts`
- Modify: `frontend/src/components/layout/Layout.tsx`
- Modify: `frontend/src/pages/Scanner.tsx`
- Modify: `frontend/src/pages/Forecast.tsx`
- Modify: `frontend/src/pages/PaperTrading.tsx`
- Modify: `frontend/src/pages/ResearchAnalysis.tsx`

**Interfaces:**
- Produces: `trackProductEvent(input)`, `flushProductEvents()`, stable local anonymous ID.
- Consumes: `POST /api/analytics/events` and existing API auth headers.

- [ ] **Step 1: Write batching and privacy tests**

```typescript
import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushProductEvents, trackProductEvent } from "../analytics";

describe("analytics transport", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("batches allowlisted fields without prompt content", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 202 }));
    trackProductEvent({ feature: "scanner", action: "result_view", outcome: "success", metadata: { route: "/scanner" } });
    await flushProductEvents();
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.events).toHaveLength(1);
    expect(JSON.stringify(body)).not.toContain("prompt");
  });
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm run test:run -- src/lib/__tests__/analytics.test.ts`

Expected: FAIL because `frontend/src/lib/analytics.ts` is missing.

- [ ] **Step 3: Implement deterministic event naming and batching**

`trackProductEvent` accepts only `feature`, `action`, `outcome`, optional `sessionId`, `durationMs`, and metadata `{route?, market?, result_count?, source?}`. Generate IDs with `crypto.randomUUID()`, store a random local ID under `alpha-mind-analytics-user`, flush at 25 events or 5 seconds, retry no failed batch, and swallow network errors. Use `authHeaders()` and `navigator.sendBeacon` only when no API auth key is required; otherwise use `fetch(batchUrl, {method: "POST", body, headers, keepalive: true})`.

In `Layout`, emit `page_view` on pathname changes. In Scanner, Forecast, Paper Trading, and Research Analysis emit `task_start`, `task_complete`, and `result_view` at the existing start/success/render boundaries. Paper Trading also emits `experiment_save` after a created run is persisted and `experiment_compare` when the comparison request succeeds. Never pass symbol, prompt, response, holdings, or strategy parameters in metadata.

- [ ] **Step 4: Add focused page assertions**

Mock `trackProductEvent` in the existing Scanner and Forecast tests and add:

```typescript
expect(trackProductEventMock.mock.calls.map(([event]) => [event.action, event.outcome])).toEqual([
  ["task_start", "unknown"],
  ["task_complete", "success"],
  ["result_view", "success"],
]);

apiMock.runScan.mockRejectedValueOnce(new Error("scan failed"));
await userEvent.click(screen.getByRole("button", { name: "更新机会" }));
await waitFor(() => expect(trackProductEventMock).toHaveBeenCalledWith(
  expect.objectContaining({ action: "task_complete", outcome: "failure" }),
));
expect(trackProductEventMock).not.toHaveBeenCalledWith(
  expect.objectContaining({ action: "result_view", outcome: "success" }),
);
```

- [ ] **Step 5: Run frontend transport and affected page tests**

Run: `cd frontend && npm run test:run -- src/lib/__tests__/analytics.test.ts src/pages/__tests__/Scanner.test.tsx src/pages/__tests__/ForecastRobustStrategy.test.tsx`

Expected: all tests PASS.

- [ ] **Step 6: Commit product instrumentation**

```bash
git add frontend/src/lib/analytics.ts frontend/src/lib/__tests__/analytics.test.ts frontend/src/components/layout/Layout.tsx frontend/src/pages/Scanner.tsx frontend/src/pages/Forecast.tsx frontend/src/pages/PaperTrading.tsx frontend/src/pages/ResearchAnalysis.tsx frontend/src/pages/__tests__/Scanner.test.tsx frontend/src/pages/__tests__/ForecastRobustStrategy.test.tsx
git commit -m "feat: instrument core research journeys"
```

### Task 6: Usage/System Analytics Page

**Files:**
- Create: `frontend/src/components/analytics/TrendChart.tsx`
- Create: `frontend/src/components/analytics/MetricCard.tsx`
- Create: `frontend/src/pages/Analytics.tsx`
- Create: `frontend/src/pages/__tests__/Analytics.test.tsx`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/echarts.ts`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/components/layout/Layout.tsx`
- Modify: `frontend/src/components/layout/__tests__/Layout.test.tsx`

**Interfaces:**
- Consumes: analytics trend, usage, and system-health APIs.
- Produces: `/analytics` route with “功能使用” and “系统健康” views.

- [ ] **Step 1: Write failing page and navigation tests**

```typescript
it("renders usage trends and switches to system health", async () => {
  apiMock.getAnalyticsUsage.mockResolvedValue(usageFixture);
  apiMock.getAnalyticsSystemHealth.mockResolvedValue(systemFixture);
  render(<Analytics />);
  expect(await screen.findByText("有效研究会话")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "系统健康" }));
  expect(await screen.findByText("P95 延迟")).toBeInTheDocument();
});
```

Add a Layout test asserting a “数据洞察” link points to `/analytics`.

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm run test:run -- src/pages/__tests__/Analytics.test.tsx src/components/layout/__tests__/Layout.test.tsx`

Expected: FAIL because the page, API methods, and navigation entry are absent.

- [ ] **Step 3: Add exact API contracts and methods**

In `api.ts`, add `AnalyticsMetricPoint`, `AnalyticsTrendResponse`, `AnalyticsUsageResponse`, and `AnalyticsSystemHealthResponse`; every response includes `data_through`, `generated_at`, `sample_count`, `calculation_version`, and `warnings`. Add `getAnalyticsTrends(metric, days)`, `getAnalyticsUsage(days)`, and `getAnalyticsSystemHealth(days)`.

- [ ] **Step 4: Build the first dashboard page**

Lazy-load `/analytics`, add a `BarChart3` navigation item labeled “数据洞察”, and implement:

```typescript
type AnalyticsView = "usage" | "system";
type AnalyticsDays = 7 | 30 | 90;
```

Render day buttons, comparison deltas, metric cards with sparklines, one full-width ECharts trend, loading skeletons, a `no_data` empty state, stale warnings, and a visible sample count in chart tooltips. The usage response includes a session funnel with steps `page_view → task_start → task_complete → result_view → experiment_save_or_compare`, each retaining distinct-session numerator and initial-session denominator. Do not add health scoring, research, development, or release markers in this plan.

- [ ] **Step 5: Run page tests and production build**

Run: `cd frontend && npm run test:run -- src/pages/__tests__/Analytics.test.tsx src/components/layout/__tests__/Layout.test.tsx && npm run build`

Expected: tests PASS and Vite build completes without TypeScript errors.

- [ ] **Step 6: Run the complete Phase 1 verification**

Run: `cd agent && ../.venv/bin/pytest tests/analytics -v`

Expected: all analytics backend tests PASS.

Run: `git status --short`

Expected: only intended Phase 1 files are modified.

- [ ] **Step 7: Commit the working Phase 1 dashboard**

```bash
git add frontend/src/components/analytics/TrendChart.tsx frontend/src/components/analytics/MetricCard.tsx frontend/src/pages/Analytics.tsx frontend/src/pages/__tests__/Analytics.test.tsx frontend/src/lib/api.ts frontend/src/lib/echarts.ts frontend/src/router.tsx frontend/src/components/layout/Layout.tsx frontend/src/components/layout/__tests__/Layout.test.tsx
git commit -m "feat: add usage and system analytics dashboard"
```
