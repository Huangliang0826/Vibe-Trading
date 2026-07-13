# Analytics Trend Data Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill up to 90 days of trustworthy local research-quality observations, keep them synchronized automatically, and explain freshness, coverage, and missing sources in the Dashboard.

**Architecture:** Read-only source adapters convert existing Scanner tracking, Backtest run artifacts, and Paper Trading runs into deterministic quality events. A best-effort coordinator writes events and per-source synchronization state into `analytics.db`; API responses expose coverage separately from metric availability, and shared React UI renders that metadata without inventing missing values.

**Tech Stack:** Python 3.11, Pydantic, SQLite/WAL, FastAPI, existing Scanner and Paper Trading stores, React, TypeScript, Vitest, pytest.

## Global Constraints

- Do not synthesize historical product usage or Forecast results.
- Do not call external models or market-data providers during backfill.
- Existing business modules remain authoritative for all financial metrics.
- Backfill is local, idempotent, best-effort, and must never block core business startup.
- Default history window is 90 calendar days; quality events retain indefinitely.
- Missing values remain `null` with a machine-readable reason; they are never converted to zero.
- No subagents are used for this execution; implement inline in the existing `codex/analytics-dashboard` worktree.

---

## File Structure

- `agent/src/analytics/models.py`: source synchronization and coverage response contracts.
- `agent/src/analytics/store.py`: source-state migration and persistence.
- `agent/src/analytics/quality_sources.py`: isolated Scanner, Backtest, and Paper Trading readers.
- `agent/src/analytics/quality_backfill.py`: idempotent source orchestration and status updates.
- `agent/src/analytics/quality_adapters.py`: mapping authoritative scalar metrics to quality events.
- `agent/src/analytics/runtime.py`: hourly best-effort synchronization.
- `agent/src/analytics/service.py`: freshness and coverage response composition.
- `agent/api_server.py`: production source wiring.
- `frontend/src/lib/api.ts`: coverage types.
- `frontend/src/components/analytics/DataCoverageSummary.tsx`: shared status UI.
- `frontend/src/components/analytics/ResearchQualityView.tsx`: research coverage rendering.
- `frontend/src/pages/Analytics.tsx`: usage/system coverage rendering.

### Task 1: Persist Source Synchronization State

**Files:**
- Modify: `agent/src/analytics/models.py`
- Modify: `agent/src/analytics/store.py`
- Modify: `agent/tests/analytics/test_store.py`

**Interfaces:**
- Produces: `SourceSyncState`, `AnalyticsStore.upsert_source_state(state)`, `AnalyticsStore.get_source_states(source=None)`.
- Consumes: existing SQLite session and UTC serialization helpers.

- [ ] **Step 1: Write failing state persistence tests**

```python
from src.analytics.models import SourceSyncState


def test_source_sync_state_round_trips_and_updates(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    first = SourceSyncState(
        source="scanner", status="available",
        last_attempted_at="2026-07-13T10:00:00Z",
        last_success_at="2026-07-13T10:00:00Z",
        data_through="2026-07-12", records_scanned=20,
        events_written=8, coverage_days=4,
    )
    store.upsert_source_state(first)
    assert store.get_source_states("scanner") == [first]
    updated = first.model_copy(update={"events_written": 0, "coverage_days": 5})
    store.upsert_source_state(updated)
    assert store.get_source_states("scanner")[0].coverage_days == 5
```

- [ ] **Step 2: Run the test to verify the contract is missing**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_store.py::test_source_sync_state_round_trips_and_updates -v`

Expected: FAIL because `SourceSyncState` and store methods do not exist.

- [ ] **Step 3: Add the model and schema migration**

Add this model to `models.py`:

```python
class SourceSyncState(BaseModel):
    source: str
    status: Literal["available", "partial", "no_data", "source_unavailable", "error"]
    last_attempted_at: str
    last_success_at: str | None = None
    data_through: str | None = None
    records_scanned: int = Field(default=0, ge=0)
    events_written: int = Field(default=0, ge=0)
    coverage_days: int = Field(default=0, ge=0)
    reason: str | None = None
```

Create `source_sync_state` with `source TEXT PRIMARY KEY` plus the exact model fields, and set `PRAGMA user_version=2`. Implement an `INSERT ... ON CONFLICT(source) DO UPDATE` method and a deterministic `ORDER BY source` query method.

- [ ] **Step 4: Run store tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_store.py -v`

Expected: all store tests PASS.

- [ ] **Step 5: Commit source state persistence**

```bash
git add agent/src/analytics/models.py agent/src/analytics/store.py agent/tests/analytics/test_store.py
git commit -m "feat: persist analytics source state"
```

### Task 2: Add Read-Only Historical Quality Sources

**Files:**
- Create: `agent/src/analytics/quality_sources.py`
- Create: `agent/tests/analytics/test_quality_sources.py`
- Modify: `agent/src/analytics/quality_adapters.py`
- Modify: `agent/tests/analytics/test_quality_adapters.py`

**Interfaces:**
- Produces: `QualitySourceResult`, `ScannerHistorySource.read(start, end)`, `BacktestHistorySource.read(start, end)`, `PaperTradingHistorySource.read(start, end)`.
- Produces: `BacktestQualityAdapter.from_metrics(...)` and `PaperTradingQualityAdapter.from_run(run)`.
- Consumes: `TrackingRecord`, `compute_accuracy`, `PaperTradingStore.list_runs`, `make_quality_event`.

- [ ] **Step 1: Write failing adapter tests**

```python
from types import SimpleNamespace


def test_backtest_adapter_preserves_authoritative_metrics():
    events = BacktestQualityAdapter().from_metrics(
        run_id="run-1", market="us", as_of=date(2026, 7, 12),
        metrics={"total_return": 0.21, "sharpe": 1.4, "max_drawdown": -0.12, "trade_count": 31},
    )
    values = {event.metadata["metric_name"]: event.metadata["metric_value"] for event in events}
    assert values == {"total_return": 0.21, "sharpe": 1.4, "max_drawdown": -0.12, "trade_count": 31.0}


def test_paper_adapter_uses_completion_date_and_trade_count():
    run = SimpleNamespace(
        run_id="paper-1", updated_at="2026-07-12T14:30:00Z",
        holdings=[SimpleNamespace(market="us")],
        experiment=SimpleNamespace(metric_version="backtest.metrics.v2"),
        metrics={"total_return": 0.15, "trade_count": 24},
    )
    events = PaperTradingQualityAdapter().from_run(run)
    assert {event.metadata["as_of"] for event in events} == {"2026-07-12"}
    assert all(event.metadata["formula_version"] == "paper.backtest.metrics.v2" for event in events)
```

- [ ] **Step 2: Write failing source tests**

```python
import csv
import json
from pathlib import Path

from src.scanner.tracking import TrackingRecord, save_tracking


def write_tracking(root: Path, universe: str, as_of: str, **returns):
    record = TrackingRecord(symbol="AAPL", score=0.8, asof=as_of, entry_price=100.0, **returns)
    save_tracking([record], as_of, root=root, universe=universe)


def write_successful_backtest(path: Path, *, total_return: float):
    artifacts = path / "artifacts"
    artifacts.mkdir(parents=True)
    (path / "state.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
    with (artifacts / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["total_return", "trade_count"])
        writer.writeheader()
        writer.writerow({"total_return": total_return, "trade_count": 21})


def test_scanner_source_hides_unmatured_forward_returns(tmp_path):
    write_tracking(tmp_path, "sp500", "2026-07-10", fwd_1d=1.0, fwd_5d=4.0)
    result = ScannerHistorySource(tmp_path, universes=("sp500",)).read(
        date(2026, 7, 11), date(2026, 7, 12)
    )
    assert not any(event.metadata["horizon"] == "5d" for event in result.events)


def test_backtest_source_skips_corrupt_run_and_reports_partial(tmp_path):
    write_successful_backtest(tmp_path / "good", total_return=0.2)
    (tmp_path / "broken" / "artifacts").mkdir(parents=True)
    (tmp_path / "broken" / "artifacts" / "metrics.csv").write_text("bad\n\"")
    result = BacktestHistorySource(tmp_path).read(date(2026, 4, 15), date(2026, 7, 13))
    assert result.status == "partial"
    assert result.records_scanned == 2
    assert result.events
```

- [ ] **Step 3: Run focused tests and confirm missing sources**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_quality_adapters.py tests/analytics/test_quality_sources.py -v`

Expected: FAIL on missing adapter and source classes.

- [ ] **Step 4: Implement adapters without financial recomputation**

Use this scalar mapping for Backtest and Paper Trading:

```python
SCALAR_METRICS = (
    "total_return", "total_return_pct", "annual_return", "annual_return_pct",
    "sharpe", "max_loss", "max_drawdown", "win_rate", "trade_count",
)
```

Preserve the exact stored numeric value, skip absent/non-finite fields, use `trade_count` as the observation sample count when present and otherwise `1`, and use `subject_id=run_id`, `horizon="run"`, `regime="all"`.

- [ ] **Step 5: Implement isolated source readers**

Define:

```python
@dataclass(frozen=True)
class QualitySourceResult:
    source: str
    status: Literal["available", "partial", "no_data", "source_unavailable", "error"]
    events: list[AnalyticsEvent]
    records_scanned: int
    data_through: str | None
    coverage_days: int
    reason: str | None = None
```

Scanner creates daily cumulative snapshots and nulls each `fwd_*` field until its existing maturity pad (2/8/15/28 calendar days) has elapsed. Backtest scans only directories whose observation date is in `[start, end]`; it reads the first row of `metrics.csv` and uses run context only to infer market. Paper Trading selects only completed runs in the same date window. Each reader catches errors per record, returns `partial` when at least one record failed, and never performs network I/O.

- [ ] **Step 6: Run focused source tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_quality_adapters.py tests/analytics/test_quality_sources.py -v`

Expected: all tests PASS.

- [ ] **Step 7: Commit quality sources**

```bash
git add agent/src/analytics/quality_adapters.py agent/src/analytics/quality_sources.py agent/tests/analytics/test_quality_adapters.py agent/tests/analytics/test_quality_sources.py
git commit -m "feat: read historical research quality"
```

### Task 3: Coordinate Backfill and Runtime Synchronization

**Files:**
- Create: `agent/src/analytics/quality_backfill.py`
- Create: `agent/tests/analytics/test_quality_backfill.py`
- Modify: `agent/src/analytics/runtime.py`
- Modify: `agent/tests/analytics/test_runtime.py`
- Modify: `agent/api_server.py`

**Interfaces:**
- Produces: `QualityBackfillCoordinator.run(reference=None, lookback_days=90) -> list[SourceSyncState]`.
- Consumes: Task 1 source-state store methods and Task 2 `QualitySourceResult` readers.

- [ ] **Step 1: Write failing idempotency and isolation tests**

```python
from datetime import date, datetime, timezone

from src.analytics.models import SourceSyncState
from src.analytics.quality import make_quality_event
from src.analytics.quality_sources import QualitySourceResult


def quality_event(subject_id: str):
    return make_quality_event(
        subject_type="scanner", subject_id=subject_id, market="us", horizon="5d",
        regime="all", metric_name="hit_rate", metric_value=0.55, sample_count=21,
        formula_version="scanner.accuracy.v1", as_of=date(2026, 7, 12),
    )


class FakeSource:
    def __init__(self, source: str, events: list):
        self.source = source
        self.events = events

    def read(self, start: date, end: date):
        return QualitySourceResult(self.source, "available", self.events, 1, end.isoformat(), 1)


class BrokenSource:
    source = "broken"

    def read(self, start: date, end: date):
        raise OSError("fixture failure")


def test_backfill_is_idempotent_and_tracks_written_count(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    source = FakeSource("scanner", [quality_event("q-1")])
    coordinator = QualityBackfillCoordinator(store, [source])
    first = coordinator.run(reference=datetime(2026, 7, 13, tzinfo=timezone.utc))
    second = coordinator.run(reference=datetime(2026, 7, 13, tzinfo=timezone.utc))
    assert first[0].events_written == 1
    assert second[0].events_written == 0
    assert len(store.query_events(kind="quality")) == 1


def test_failed_source_does_not_block_other_sources(tmp_path):
    store = AnalyticsStore(tmp_path / "analytics.db")
    states = QualityBackfillCoordinator(store, [BrokenSource(), FakeSource("backtest", [quality_event("q-2")])]).run()
    assert {state.source: state.status for state in states} == {"backtest": "available", "broken": "error"}
    assert len(store.query_events(kind="quality")) == 1
```

- [ ] **Step 2: Run coordinator tests and verify failure**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_quality_backfill.py -v`

Expected: FAIL because the coordinator does not exist.

- [ ] **Step 3: Implement the coordinator**

For every source, call `read(start_date, reference.date())`, append its events, and persist a `SourceSyncState`. Keep the previous `last_success_at` when a run errors; set it to the current UTC time for `available`, `partial`, or `no_data`. Add a synthetic Forecast source state by querying existing `quality` events with `feature="forecast"`; report `source_unavailable` and reason `no_persisted_forecast_history` when none exist.

- [ ] **Step 4: Add best-effort runtime scheduling**

Extend `AnalyticsRuntime.__init__` with `quality_backfill: QualityBackfillCoordinator | None = None`. On the first loop and every hour:

```python
if self.quality_backfill is not None:
    try:
        await asyncio.to_thread(self.quality_backfill.run)
    except Exception as exc:
        logger.warning("analytics quality backfill failed with %s", type(exc).__name__)
```

Run it before `rollup.run_missing_days`; keep all existing collector behavior unchanged.

- [ ] **Step 5: Wire production sources**

In `api_server.py`, construct the coordinator with Scanner tracking root, `RUNS_DIR`, and `_get_paper_trading_store()`. Pass it to `AnalyticsRuntime` only when `ANALYTICS_ENABLED` is enabled. Construction must not scan files; scanning happens in the runtime thread.

- [ ] **Step 6: Run coordinator and runtime tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_quality_backfill.py tests/analytics/test_runtime.py tests/analytics/test_provider_observation.py -v`

Expected: all tests PASS, including a test proving a thrown backfill exception does not stop a later collector flush.

- [ ] **Step 7: Commit automatic synchronization**

```bash
git add agent/src/analytics/quality_backfill.py agent/src/analytics/runtime.py agent/api_server.py agent/tests/analytics/test_quality_backfill.py agent/tests/analytics/test_runtime.py
git commit -m "feat: synchronize analytics quality history"
```

### Task 4: Expose Freshness and Coverage Metadata

**Files:**
- Modify: `agent/src/analytics/store.py`
- Modify: `agent/src/analytics/service.py`
- Modify: `agent/tests/analytics/test_research_api.py`
- Modify: `agent/tests/analytics/test_routes.py`

**Interfaces:**
- Produces: `freshness: "fresh" | "stale" | "no_data"` and a `coverage` object on usage, system health, and research quality responses.
- Consumes: source states and existing event/metric buckets.

- [ ] **Step 1: Write failing API coverage tests**

```python
def test_research_api_reports_source_coverage_and_freshness(tmp_path):
    client, store = research_client(tmp_path)
    seed_quality(store, subject="scanner", market="us", horizon="5d", metric="hit_rate", value=0.57, sample_count=21)
    store.upsert_source_state(SourceSyncState(
        source="scanner", status="available",
        last_attempted_at="2026-07-13T10:00:00Z", last_success_at="2026-07-13T10:00:00Z",
        data_through="2026-07-13", records_scanned=21, events_written=1, coverage_days=1,
    ))
    body = client.get("/api/analytics/research-quality?days=30&subject=scanner&market=us&horizon=5d").json()
    assert body["freshness"] == "fresh"
    assert body["coverage"]["window_days"] == 30
    assert body["coverage"]["covered_days"] == 1
    assert body["coverage"]["sources"][0]["source"] == "scanner"
```

- [ ] **Step 2: Run API tests and verify missing metadata**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_research_api.py tests/analytics/test_routes.py -v`

Expected: FAIL because `freshness` and `coverage` are absent.

- [ ] **Step 3: Implement coverage composition**

For research, count distinct `bucket` values after filters and include only the selected subject source state. For usage/system, count distinct metric-point buckets and return a derived source entry named `product_events` or `system_events`. Use:

```python
coverage = {
    "window_days": days,
    "covered_days": covered_days,
    "coverage_rate": covered_days / days,
    "sources": [state.model_dump(mode="json") for state in states],
}
```

`freshness` is `no_data` when `data_through` is null, `stale` when it is more than two calendar days before today or the selected state has status `error`, and otherwise `fresh`. Append `stale_data` to warnings without removing existing warning codes.

- [ ] **Step 4: Run API tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_research_api.py tests/analytics/test_routes.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit API metadata**

```bash
git add agent/src/analytics/store.py agent/src/analytics/service.py agent/tests/analytics/test_research_api.py agent/tests/analytics/test_routes.py
git commit -m "feat: expose analytics data coverage"
```

### Task 5: Render Coverage and Missing Reasons

**Files:**
- Create: `frontend/src/components/analytics/DataCoverageSummary.tsx`
- Create: `frontend/src/components/analytics/__tests__/DataCoverageSummary.test.tsx`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/analytics/ResearchQualityView.tsx`
- Modify: `frontend/src/components/analytics/__tests__/ResearchQualityView.test.tsx`
- Modify: `frontend/src/pages/Analytics.tsx`
- Modify: `frontend/src/pages/__tests__/Analytics.test.tsx`

**Interfaces:**
- Produces: `<DataCoverageSummary freshness coverage />`.
- Consumes: Task 4 API metadata.

- [ ] **Step 1: Write failing component tests**

```tsx
it("explains partial coverage without showing a fake zero", () => {
  render(<DataCoverageSummary freshness="stale" coverage={{
    window_days: 30, covered_days: 7, coverage_rate: 7 / 30,
    sources: [{ source: "forecast", status: "source_unavailable", last_attempted_at: "2026-07-13T10:00:00Z", last_success_at: null, data_through: null, records_scanned: 0, events_written: 0, coverage_days: 0, reason: "no_persisted_forecast_history" }],
  }} />);
  expect(screen.getByText("覆盖 7 / 30 天")).toBeInTheDocument();
  expect(screen.getByText("暂无可回填的 Forecast 历史；新结果将从现在开始积累。")).toBeInTheDocument();
  expect(screen.queryByText("0% 准确率")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run frontend tests and verify missing component**

Run: `cd frontend && npm test -- --run src/components/analytics/__tests__/DataCoverageSummary.test.tsx src/components/analytics/__tests__/ResearchQualityView.test.tsx src/pages/__tests__/Analytics.test.tsx`

Expected: FAIL because coverage types and component are missing.

- [ ] **Step 3: Add typed coverage contracts**

Add `AnalyticsSourceState`, `AnalyticsCoverage`, and `AnalyticsFreshness` to `frontend/src/lib/api.ts`; add `freshness` and `coverage` to trend and research responses.

- [ ] **Step 4: Implement shared coverage UI**

Render a compact line with covered/window days, `data_through`, and last successful sync. Map reasons exactly:

```ts
const REASONS: Record<string, string> = {
  no_persisted_forecast_history: "暂无可回填的 Forecast 历史；新结果将从现在开始积累。",
  no_local_records: "本地暂时没有可用历史记录。",
  parse_errors: "部分历史文件无法读取，已展示其余可用数据。",
};
```

Use neutral styling for fresh, amber for stale/partial, and muted styling for no data. Never render a numeric value for a missing observation.

- [ ] **Step 5: Place the component in all three views**

Render it above usage/system charts in `Analytics.tsx` and above research status/cards in `ResearchQualityView.tsx`. Keep all current empty-state and sample-threshold behavior.

- [ ] **Step 6: Run focused frontend tests**

Run: `cd frontend && npm test -- --run src/components/analytics/__tests__/DataCoverageSummary.test.tsx src/components/analytics/__tests__/ResearchQualityView.test.tsx src/pages/__tests__/Analytics.test.tsx`

Expected: all tests PASS.

- [ ] **Step 7: Commit coverage UI**

```bash
git add frontend/src/lib/api.ts frontend/src/components/analytics/DataCoverageSummary.tsx frontend/src/components/analytics/__tests__/DataCoverageSummary.test.tsx frontend/src/components/analytics/ResearchQualityView.tsx frontend/src/components/analytics/__tests__/ResearchQualityView.test.tsx frontend/src/pages/Analytics.tsx frontend/src/pages/__tests__/Analytics.test.tsx
git commit -m "feat: explain analytics data coverage"
```

### Task 6: Full Verification

**Files:**
- Modify only if verification reveals a concrete defect.

- [ ] **Step 1: Run all Analytics backend tests**

Run: `cd agent && ../.venv/bin/pytest tests/analytics -q`

Expected: all tests PASS.

- [ ] **Step 2: Run the complete backend suite**

Run: `cd agent && ../.venv/bin/pytest -q`

Expected: all tests PASS with only previously known deprecation warnings.

- [ ] **Step 3: Run the complete frontend suite**

Run: `cd frontend && npm test -- --run`

Expected: all tests PASS.

- [ ] **Step 4: Build the production frontend**

Run: `cd frontend && npm run build`

Expected: TypeScript and Vite build complete successfully; the existing chart chunk-size warning is allowed.

- [ ] **Step 5: Exercise idempotent backfill against temporary fixtures**

Run: `cd agent && ../.venv/bin/pytest tests/analytics/test_quality_backfill.py::test_backfill_is_idempotent_and_tracks_written_count -v`

Expected: PASS with first write count `1` and second write count `0`.

- [ ] **Step 6: Confirm a clean worktree and record final commits**

Run: `git status --short && git log --oneline -8`

Expected: no uncommitted files and the source, coordinator, API, and frontend commits are present.
