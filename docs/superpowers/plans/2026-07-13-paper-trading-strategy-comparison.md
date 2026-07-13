# Paper Trading Strategy Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing paper-trading screen the default “历史回测” Tab and add a reproducible comparison of SPY buy-and-hold, SPY/现金 200-day timing, and defensive stock momentum Strategy V0.

**Architecture:** Keep existing historical-backtest state and markup inside `PaperTrading.tsx`, while placing the new comparison UI and charts in focused components. Add pure pandas strategy functions, a JSON-backed asynchronous comparison service with deterministic cache identity, and a small FastAPI route module; every strategy consumes the same aligned prices, capital, cost model, and next-session execution convention.

**Tech Stack:** Python 3.13, pandas, Pydantic v2, FastAPI, pytest, React 19, TypeScript, Vitest, Testing Library, ECharts

## Global Constraints

- `历史回测` is the first and default Tab; refreshing does not persist the prior Tab.
- The current paper-trading screen and its behavior remain intact inside `历史回测`.
- Comparison defaults to today minus five calendar years through today, with 1Y/3Y/5Y/10Y and custom dates.
- A comparison shorter than one year is rejected.
- All strategies use the same initial capital, date window, adjusted-price convention, trading calendar, one-way cost, and zero cash yield.
- Signals computed after a close execute no earlier than the next available session open.
- Strategy V0 rules are fixed: top-200 trailing 60-day dollar-volume universe, price above $5, 252-day history, price above SMA200, top-15 12-1 momentum, weekly rebalance, inverse 20-day volatility, 8% name cap, and SPY-driven 90%/30% gross exposure.
- The current S&P 500 constituent source is explicitly marked `survivorship_bias=true`, dated `2026-05-17`, and can never produce a formal `PASS`.
- Strategy V0 uses cash rather than an ETF short hedge in this release.
- Do not add named event windows, Hong Kong Strategy V0, cash interest, tax modeling, parameter optimization, or automatic winner selection.

---

### Task 1: Define comparison contracts and persistent run storage

**Files:**
- Create: `agent/src/paper_trading/comparison_models.py`
- Create: `agent/src/paper_trading/comparison_storage.py`
- Create: `agent/tests/test_strategy_comparison_storage.py`

**Interfaces:**
- Produces: `StrategyComparisonCreate`, `StrategyComparisonRun`, `StrategyResult`, `ComparisonPoint`, `ComparisonMetrics`, `ComparisonStatus`, and `StrategyComparisonStore`.
- Storage methods: `create_or_reuse(payload) -> StrategyComparisonRun`, `get(run_id) -> StrategyComparisonRun | None`, `save(run) -> StrategyComparisonRun`.

- [ ] **Step 1: Write failing model and storage tests**

```python
from datetime import date

import pytest
from pydantic import ValidationError

from src.paper_trading.comparison_models import (
    ComparisonStatus,
    StrategyComparisonCreate,
)
from src.paper_trading.comparison_storage import StrategyComparisonStore


def test_comparison_rejects_windows_shorter_than_one_year():
    with pytest.raises(ValidationError):
        StrategyComparisonCreate(
            start_date="2025-01-01",
            end_date="2025-06-30",
            initial_capital=100_000,
            cost_bps=20,
        )


def test_store_reuses_identical_completed_request(tmp_path):
    store = StrategyComparisonStore(tmp_path / "comparisons")
    payload = StrategyComparisonCreate(
        start_date="2020-01-01",
        end_date="2025-01-02",
        initial_capital=100_000,
        cost_bps=20,
    )
    first = store.create_or_reuse(payload)
    first.status = ComparisonStatus.completed
    store.save(first)
    second = store.create_or_reuse(payload)
    assert second.run_id == first.run_id
    assert second.cache_hit is True


def test_store_rejects_invalid_run_id(tmp_path):
    store = StrategyComparisonStore(tmp_path / "comparisons")
    with pytest.raises(ValueError, match="invalid comparison run id"):
        store.get("../../secret")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_storage.py -q
```

Expected: collection fails because `comparison_models` and `comparison_storage` do not exist.

- [ ] **Step 3: Implement Pydantic contracts**

Create `comparison_models.py` with these exact public fields:

```python
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

STRATEGY_COMPARISON_VERSION = "paper-comparison.v1"
UNIVERSE_SOURCE_DATE = "2026-05-17"


class ComparisonStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    partial = "partial"
    failed = "failed"


class StrategyComparisonCreate(BaseModel):
    start_date: date
    end_date: date
    initial_capital: float = Field(default=100_000, gt=0)
    cost_bps: float = Field(default=20, ge=0, le=500)

    @model_validator(mode="after")
    def validate_window(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if (self.end_date - self.start_date).days < 365:
            raise ValueError("comparison window must be at least one year")
        return self


class ComparisonPoint(BaseModel):
    date: str
    equity: float
    normalized: float
    drawdown: float
    stock_exposure: float
    cash_ratio: float


class ComparisonMetrics(BaseModel):
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    calmar: float
    annual_vol: float
    worst_year: float | None
    monthly_win_rate: float | None
    turnover: float
    transaction_cost: float
    average_cash_ratio: float
    minimum_cash_ratio: float
    annual_returns: dict[str, float] = Field(default_factory=dict)


class StrategyResult(BaseModel):
    key: Literal["spy_buy_hold", "spy_ma200", "defensive_momentum_v0"]
    label: str
    status: Literal["completed", "unavailable"]
    metrics: ComparisonMetrics | None = None
    points: list[ComparisonPoint] = Field(default_factory=list)
    error: str | None = None
    coverage_rate: float = 0


class ScorecardItem(BaseModel):
    key: str
    label: str
    status: Literal["pass", "fail", "unknown", "preliminary"]
    detail: str


class StrategyComparisonRun(BaseModel):
    run_id: str
    status: ComparisonStatus = ComparisonStatus.queued
    request: StrategyComparisonCreate
    created_at: str
    updated_at: str
    cache_key: str
    cache_hit: bool = False
    calculation_version: str = STRATEGY_COMPARISON_VERSION
    survivorship_bias: bool = True
    universe_source_date: str = UNIVERSE_SOURCE_DATE
    data_through: str | None = None
    results: list[StrategyResult] = Field(default_factory=list)
    scorecard: list[ScorecardItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
```

- [ ] **Step 4: Implement deterministic JSON storage**

Create `comparison_storage.py`. Hash the normalized request together with `STRATEGY_COMPARISON_VERSION` and `UNIVERSE_SOURCE_DATE`. Persist each run at `<root>/<run_id>.json` and a cache index at `<root>/cache-index.json`. Only reuse `completed` or `partial` runs.

```python
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.config.paths import get_runtime_root
from src.paper_trading.comparison_models import (
    ComparisonStatus, STRATEGY_COMPARISON_VERSION, UNIVERSE_SOURCE_DATE,
    StrategyComparisonCreate, StrategyComparisonRun, utc_now,
)


class StrategyComparisonStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (get_runtime_root() / "paper_strategy_comparisons")
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "cache-index.json"

    def _cache_key(self, payload: StrategyComparisonCreate) -> str:
        identity = {
            "request": payload.model_dump(mode="json"),
            "calculation_version": STRATEGY_COMPARISON_VERSION,
            "universe_source_date": UNIVERSE_SOURCE_DATE,
        }
        raw = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def _path(self, run_id: str) -> Path:
        if not re.fullmatch(r"comparison-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", run_id):
            raise ValueError("invalid comparison run id")
        return self.root / f"{run_id}.json"

    def _index(self) -> dict[str, str]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def create_or_reuse(self, payload: StrategyComparisonCreate) -> StrategyComparisonRun:
        key = self._cache_key(payload)
        cached_id = self._index().get(key)
        if cached_id:
            cached = self.get(cached_id)
            if cached and cached.status in {ComparisonStatus.completed, ComparisonStatus.partial}:
                cached.cache_hit = True
                return cached
        now = utc_now()
        run_id = f"comparison-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
        run = StrategyComparisonRun(
            run_id=run_id, request=payload, created_at=now, updated_at=now, cache_key=key,
        )
        return self.save(run)

    def get(self, run_id: str) -> StrategyComparisonRun | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        return StrategyComparisonRun.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, run: StrategyComparisonRun) -> StrategyComparisonRun:
        run.updated_at = utc_now()
        self._path(run.run_id).write_text(run.model_dump_json(indent=2), encoding="utf-8")
        if run.status in {ComparisonStatus.completed, ComparisonStatus.partial}:
            index = self._index()
            index[run.cache_key] = run.run_id
            self.index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        return run
```

- [ ] **Step 5: Verify GREEN and commit**

Run `cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_storage.py -q`.
Expected: 3 passed.

```bash
git add agent/src/paper_trading/comparison_models.py agent/src/paper_trading/comparison_storage.py agent/tests/test_strategy_comparison_storage.py
git commit -m "feat: persist strategy comparison runs"
```

### Task 2: Implement a shared next-session portfolio simulator and SPY baselines

**Files:**
- Create: `agent/src/paper_trading/comparison_engine.py`
- Create: `agent/tests/test_strategy_comparison_engine.py`

**Interfaces:**
- Produces: `SimulationResult`, `simulate_weight_schedule`, `build_spy_buy_hold_targets`, `build_spy_ma200_targets`, and `summarize_simulation`.
- Consumes: aligned open/close DataFrames with project symbols as columns.

- [ ] **Step 1: Write failing timing and baseline tests**

```python
import pandas as pd
import pytest

from src.paper_trading.comparison_engine import (
    build_spy_ma200_targets,
    simulate_weight_schedule,
)


def test_close_signal_executes_at_next_open():
    index = pd.bdate_range("2024-01-02", periods=202)
    close = pd.DataFrame({"SPY.US": [100.0] * 200 + [101.0, 102.0]}, index=index)
    open_ = close.copy()
    open_.iloc[-1, 0] = 120.0
    targets = build_spy_ma200_targets(close["SPY.US"])
    result = simulate_weight_schedule(open_, close, targets, index[-1], 100_000, 0)
    assert result.equity.index[0] == index[-1]
    assert result.equity.iloc[0] == pytest.approx(100_000)
    assert result.shares.iloc[0]["SPY.US"] == pytest.approx(100_000 / 120.0)


def test_one_way_cost_is_charged_on_turnover():
    index = pd.bdate_range("2024-01-02", periods=3)
    prices = pd.DataFrame({"SPY.US": [100.0, 100.0, 100.0]}, index=index)
    targets = pd.DataFrame({"SPY.US": [1.0, 1.0, 1.0]}, index=index)
    result = simulate_weight_schedule(prices, prices, targets, index[1], 100_000, 20)
    assert result.transaction_cost == pytest.approx(200.0)
    assert result.equity.iloc[0] == pytest.approx(99_800.0)
```

- [ ] **Step 2: Run tests and verify RED**

Run `cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_engine.py -q`.
Expected: import failure for `comparison_engine`.

- [ ] **Step 3: Implement the simulator and baseline target schedules**

Use a full daily target schedule and shift it one row before execution. Rebalance only when shifted target weights change. At each rebalance, calculate target dollars from pre-trade open equity, charge `abs(delta_dollars) * cost_bps / 10_000`, and leave all unallocated value in cash.

```python
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.metrics import calc_metrics
from src.paper_trading.comparison_models import ComparisonMetrics, ComparisonPoint


@dataclass
class SimulationResult:
    equity: pd.Series
    shares: pd.DataFrame
    stock_exposure: pd.Series
    cash_ratio: pd.Series
    turnover: float
    transaction_cost: float


def build_spy_buy_hold_targets(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"SPY.US": 1.0}, index=index)


def build_spy_ma200_targets(spy_close: pd.Series) -> pd.DataFrame:
    invested = (spy_close > spy_close.rolling(200, min_periods=200).mean()).astype(float)
    return invested.to_frame("SPY.US")


def simulate_weight_schedule(open_prices, close_prices, targets, start_date, initial_capital, cost_bps):
    index = open_prices.index.intersection(close_prices.index).sort_values()
    symbols = list(open_prices.columns.intersection(close_prices.columns))
    open_prices = open_prices.reindex(index)[symbols]
    close_prices = close_prices.reindex(index)[symbols]
    daily_targets = targets.reindex(index).ffill().fillna(0.0).reindex(columns=symbols, fill_value=0.0)
    execution_targets = daily_targets.shift(1).fillna(0.0)
    active = index[index >= pd.Timestamp(start_date)]
    holdings = pd.Series(0.0, index=symbols)
    cash = float(initial_capital)
    last_target = pd.Series(np.nan, index=symbols)
    rows, share_rows, exposure_rows, cash_rows = [], [], [], []
    total_turnover = 0.0
    total_cost = 0.0
    for ts in active:
        opens = open_prices.loc[ts]
        closes = close_prices.loc[ts]
        target = execution_targets.loc[ts].fillna(0.0).clip(lower=0.0)
        if not target.equals(last_target):
            pretrade = cash + float((holdings * opens.fillna(closes)).sum())
            current_value = holdings * opens.fillna(closes)
            target_value = target * pretrade
            delta = target_value - current_value
            traded = float(delta.abs().sum())
            cost = traded * float(cost_bps) / 10_000.0
            valid = opens.replace(0, np.nan)
            holdings = (target_value / valid).fillna(holdings)
            cash = pretrade - float(target_value.sum()) - cost
            total_turnover += traded / max(pretrade, 1e-12)
            total_cost += cost
            last_target = target
        equity = cash + float((holdings * closes).sum())
        stock_value = float((holdings * closes).sum())
        rows.append((ts, equity))
        share_rows.append(holdings.copy())
        exposure_rows.append(stock_value / equity if equity else 0.0)
        cash_rows.append(cash / equity if equity else 1.0)
    return SimulationResult(
        equity=pd.Series(dict(rows), dtype=float),
        shares=pd.DataFrame(share_rows, index=active),
        stock_exposure=pd.Series(exposure_rows, index=active, dtype=float),
        cash_ratio=pd.Series(cash_rows, index=active, dtype=float),
        turnover=total_turnover,
        transaction_cost=total_cost,
    )
```

Add `summarize_simulation(result, initial_capital)` using `calc_metrics(result.equity, [], initial_capital)`. Derive calendar-year returns with `equity.resample("YE").last().pct_change()`, monthly win rate from `equity.resample("ME").last().pct_change()`, and `ComparisonPoint` rows from the same equity curve and its cumulative maximum. Map `annual_return` to `cagr`; never recalculate metrics in the frontend.

- [ ] **Step 4: Verify engine tests and commit**

Run `cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_engine.py -q`.
Expected: timing and cost tests pass.

```bash
git add agent/src/paper_trading/comparison_engine.py agent/tests/test_strategy_comparison_engine.py
git commit -m "feat: simulate comparable SPY strategies"
```

### Task 3: Implement fixed defensive momentum targets

**Files:**
- Modify: `agent/src/paper_trading/comparison_engine.py`
- Modify: `agent/tests/test_strategy_comparison_engine.py`

**Interfaces:**
- Produces: `build_defensive_momentum_targets(close, volume, spy_close) -> pd.DataFrame` and `capped_inverse_vol_weights(volatility, gross, cap) -> pd.Series`.
- The target DataFrame uses signal dates; `simulate_weight_schedule` enforces next-session execution.

- [ ] **Step 1: Add failing selection, cap, cash-regime, and no-lookahead tests**

Create deterministic 280-session panels for 20 symbols. Assert that only the top 15 eligible momentum names receive weights, each weight is `<= 0.08`, total weight is `0.90` in SPY risk-on and `0.30` in risk-off, and modifying prices after a signal date does not change that signal row.

```python
def momentum_fixture():
    index = pd.bdate_range("2023-01-02", periods=320)
    symbols = [f"S{i:02d}.US" for i in range(20)]
    close = pd.DataFrame(
        {
            symbol: np.linspace(20 + i, 45 + i * 2, len(index))
            for i, symbol in enumerate(symbols)
        },
        index=index,
    )
    volume = pd.DataFrame(
        {symbol: 1_000_000 + i * 10_000 for i, symbol in enumerate(symbols)},
        index=index,
    )
    spy = pd.Series(np.linspace(100, 160, len(index)), index=index, name="SPY.US")
    spy.iloc[-5:] = 50.0
    return index, close, volume, spy


def test_defensive_momentum_is_capped_and_respects_spy_regime():
    index, close, volume, spy = momentum_fixture()
    targets = build_defensive_momentum_targets(close, volume, spy)
    risk_on = targets.dropna(how="all").iloc[-2]
    risk_off = targets.dropna(how="all").iloc[-1]
    assert (risk_on[risk_on > 0] <= 0.08 + 1e-12).all()
    assert (risk_off[risk_off > 0] <= 0.08 + 1e-12).all()
    assert risk_on.sum() == pytest.approx(0.90)
    assert risk_off.sum() == pytest.approx(0.30)
    assert (risk_on > 0).sum() == 15


def test_momentum_signal_does_not_change_when_future_prices_change():
    index, close, volume, spy = momentum_fixture()
    first = build_defensive_momentum_targets(close, volume, spy)
    signal_day = first.index[-2]
    changed = close.copy()
    changed.loc[changed.index > signal_day] *= 10
    second = build_defensive_momentum_targets(changed, volume, spy)
    pd.testing.assert_series_equal(first.loc[signal_day], second.loc[signal_day])
```

- [ ] **Step 2: Run tests and verify RED**

Run `cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_engine.py -q`.
Expected: missing `build_defensive_momentum_targets` and `capped_inverse_vol_weights`.

- [ ] **Step 3: Implement the exact V0 target builder**

```python
def capped_inverse_vol_weights(volatility: pd.Series, gross: float, cap: float) -> pd.Series:
    valid = volatility.replace([np.inf, -np.inf], np.nan).dropna()
    valid = valid[valid > 0]
    weights = pd.Series(0.0, index=volatility.index)
    remaining = set(valid.index)
    budget = float(gross)
    while remaining and budget > 1e-12:
        inv = 1.0 / valid.loc[list(remaining)]
        proposal = inv / inv.sum() * budget
        capped = proposal[proposal >= cap]
        if capped.empty:
            weights.loc[proposal.index] = proposal
            break
        weights.loc[capped.index] = cap
        budget -= cap * len(capped)
        remaining -= set(capped.index)
    return weights


def build_defensive_momentum_targets(close, volume, spy_close):
    close = close.sort_index()
    volume = volume.reindex_like(close)
    dollar_volume = (close * volume).rolling(60, min_periods=60).mean()
    momentum = close.shift(21) / close.shift(252) - 1.0
    sma200 = close.rolling(200, min_periods=200).mean()
    volatility = close.pct_change().rolling(20, min_periods=20).std()
    spy_sma200 = spy_close.rolling(200, min_periods=200).mean()
    weekly_dates = close.groupby(close.index.to_period("W-FRI")).apply(lambda frame: frame.index[-1])
    rows = []
    for ts in pd.DatetimeIndex(weekly_dates):
        liquid = dollar_volume.loc[ts].dropna().nlargest(200).index
        eligible = liquid[
            (close.loc[ts, liquid] > 5)
            & (close.loc[ts, liquid] > sma200.loc[ts, liquid])
            & momentum.loc[ts, liquid].notna()
        ]
        selected = momentum.loc[ts, eligible].nlargest(15).index
        gross = 0.90 if spy_close.loc[ts] > spy_sma200.loc[ts] else 0.30
        weights = capped_inverse_vol_weights(volatility.loc[ts, selected], gross, 0.08)
        row = pd.Series(0.0, index=close.columns, name=ts)
        row.loc[weights.index] = weights
        rows.append(row)
    return pd.DataFrame(rows).sort_index()
```

If fewer than 15 stocks are eligible, use all eligible names and leave unallocated gross exposure as cash. Do not redistribute above the 8% cap.

- [ ] **Step 4: Verify all engine tests and commit**

Run `cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_engine.py -q`.

```bash
git add agent/src/paper_trading/comparison_engine.py agent/tests/test_strategy_comparison_engine.py
git commit -m "feat: add defensive momentum comparison strategy"
```

### Task 4: Orchestrate data loading, partial results, scorecard, and caching

**Files:**
- Create: `agent/src/paper_trading/comparison_service.py`
- Create: `agent/tests/test_strategy_comparison_service.py`

**Interfaces:**
- Produces: `run_strategy_comparison(run_id, store, universe_loader=_load_universe_panel, spy_loader=...) -> StrategyComparisonRun`.
- Consumes: Tasks 1–3 models, storage, target builders, simulator, and summarizer.

- [ ] **Step 1: Write failing service tests with injected in-memory loaders**

Test one complete result, one `partial` result when the stock panel fails, a failed result when SPY fails, preservation of the survivorship warning, and scorecard `preliminary` rather than formal pass.

```python
def comparison_run(tmp_path):
    store = StrategyComparisonStore(tmp_path / "comparisons")
    run = store.create_or_reuse(StrategyComparisonCreate(
        start_date="2020-01-02", end_date="2025-01-03",
        initial_capital=100_000, cost_bps=20,
    ))
    return store, run


def spy_fixture_loader(_start, _end):
    index = pd.bdate_range("2018-01-02", periods=1800)
    close = pd.Series(np.linspace(100, 250, len(index)), index=index)
    return pd.DataFrame({
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close,
        "low": close,
        "close": close,
        "volume": 10_000_000,
    }, index=index)


def test_service_keeps_spy_results_when_momentum_data_fails(tmp_path):
    store, run = comparison_run(tmp_path)
    result = run_strategy_comparison(
        run.run_id,
        store,
        universe_loader=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("panel down")),
        spy_loader=spy_fixture_loader,
    )
    assert result.status == ComparisonStatus.partial
    assert [item.key for item in result.results] == ["spy_buy_hold", "spy_ma200", "defensive_momentum_v0"]
    assert result.results[-1].status == "unavailable"
    assert result.survivorship_bias is True
    assert all(item.status != "pass" for item in result.scorecard if item.key == "formal_validation")
```

- [ ] **Step 2: Run tests and verify RED**

Run `cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_service.py -q`.
Expected: import failure for `comparison_service`.

- [ ] **Step 3: Implement orchestration**

Use `pd.DateOffset(days=500)` for the fetch start, call `_load_universe_panel("sp500", f"{fetch_start}/{end}")`, and load `SPY.US` through `resolve_loader("us_equity").fetch(["SPY.US"], fetch_start, end)`. Normalize the returned SPY frame to the same open/close index. Run SPY baselines first so a stock-panel failure can still yield a partial result.

The service must set `running` before work, catch SPY failures as full `failed`, catch momentum failures into an unavailable `StrategyResult`, set `completed` only when all three results complete, and persist after every terminal state. Build Scorecard entries from the V0 metrics:

```python
checks = [
    ("max_drawdown", "最大回撤不超过 12%", metrics.max_drawdown >= -0.12),
    ("sharpe", "Sharpe 不低于 0.8", metrics.sharpe >= 0.8),
    ("positive_after_cost", "扣除成本后收益为正", metrics.total_return > 0),
    ("risk_adjusted_vs_timing", "风险调整收益超过 SPY / 现金轮动", metrics.calmar > timing.metrics.calmar),
]
```

Map true/false to `preliminary`/`fail` because `survivorship_bias` is true. Add a separate `formal_validation` item with `unknown` and the fixed bias explanation. Copy `_meta.constituent_source_date`, data coverage, unresolved symbols, and the zero-cash-yield assumption into warnings. Never convert unavailable results to zero metrics.

- [ ] **Step 4: Verify service and all comparison backend tests**

Run:

```bash
cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_storage.py tests/test_strategy_comparison_engine.py tests/test_strategy_comparison_service.py -q
```

- [ ] **Step 5: Commit**

```bash
git add agent/src/paper_trading/comparison_service.py agent/tests/test_strategy_comparison_service.py
git commit -m "feat: orchestrate paper strategy comparisons"
```

### Task 5: Expose asynchronous comparison routes

**Files:**
- Create: `agent/src/api/strategy_comparison_routes.py`
- Create: `agent/tests/test_strategy_comparison_routes.py`
- Modify: `agent/api_server.py`

**Interfaces:**
- POST `/paper-trading/strategy-comparisons` accepts `StrategyComparisonCreate` and returns `StrategyComparisonRun` with HTTP 202 for new work or HTTP 200 for a cache hit.
- GET `/paper-trading/strategy-comparisons/{run_id}` returns the current run or 404.

- [ ] **Step 1: Write failing FastAPI route tests**

Build a small FastAPI app with `register_strategy_comparison_routes`, an injected temporary store, and an executor stub. Assert validation errors, queued creation, cache-hit status, GET, and invalid/unknown IDs.

```python
@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    store = StrategyComparisonStore(tmp_path / "comparisons")

    def executor(run_id, target_store):
        run = target_store.get(run_id)
        assert run is not None
        run.status = ComparisonStatus.completed
        target_store.save(run)

    register_strategy_comparison_routes(
        app,
        require_auth=lambda: None,
        store=store,
        executor=executor,
    )
    return TestClient(app)


def test_create_and_get_comparison(client):
    response = client.post("/paper-trading/strategy-comparisons", json={
        "start_date": "2020-01-01", "end_date": "2025-01-02",
        "initial_capital": 100000, "cost_bps": 20,
    })
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert client.get(f"/paper-trading/strategy-comparisons/{run_id}").status_code == 200


def test_short_window_is_rejected(client):
    response = client.post("/paper-trading/strategy-comparisons", json={
        "start_date": "2025-01-01", "end_date": "2025-06-01",
    })
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests and verify RED**

Run `cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_routes.py -q`.

- [ ] **Step 3: Implement route registration**

Create a router module following `historical_event_routes.py`: keep strong references to background tasks, call `asyncio.to_thread(run_strategy_comparison, ...)`, remove completed tasks, set `Cache-Control: no-store`, and translate invalid run IDs to 400 and missing runs to 404.

Register it in `api_server.py` after the existing paper-trading routes:

```python
from src.api.strategy_comparison_routes import register_strategy_comparison_routes

register_strategy_comparison_routes(
    app,
    require_auth=require_local_or_auth,
)
```

- [ ] **Step 4: Verify route and existing paper-trading tests**

Run:

```bash
cd agent && ../.venv/bin/pytest tests/test_strategy_comparison_routes.py tests/test_paper_trading_storage.py tests/test_paper_trading_lookahead.py -q
```

- [ ] **Step 5: Commit**

```bash
git add agent/src/api/strategy_comparison_routes.py agent/api_server.py agent/tests/test_strategy_comparison_routes.py
git commit -m "feat: expose paper strategy comparison API"
```

### Task 6: Add frontend contracts and the default historical-backtest Tab

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/PaperTrading.tsx`
- Create: `frontend/src/components/paper-trading/StrategyComparisonTab.tsx`
- Create: `frontend/src/pages/__tests__/PaperTradingTabs.test.tsx`

**Interfaces:**
- Produces: TypeScript equivalents of all Task 1 response contracts plus `api.createStrategyComparison()` and `api.getStrategyComparison()`.
- `PaperTrading` owns `type PaperTradingTab = "history" | "comparison"` with default `history`.

- [ ] **Step 1: Write the failing page test**

Mock the API calls made by the existing page and mock `StrategyComparisonTab` with a marker. Assert the first/default Tab is history, the existing “投资组合” content is present, and clicking “策略比较” shows the marker.

```tsx
vi.mock("@/components/paper-trading/StrategyComparisonTab", () => ({
  StrategyComparisonTab: () => <div>统一策略比较内容</div>,
}));

it("keeps the existing backtest as the first and default tab", async () => {
  render(<PaperTrading />);
  const tabs = screen.getAllByRole("button")
    .map((button) => button.textContent)
    .filter((name) => ["历史回测", "策略比较"].includes(name || ""));
  expect(tabs).toEqual(["历史回测", "策略比较"]);
  expect(screen.getByText("投资组合")).toBeInTheDocument();
  expect(screen.queryByText("统一策略比较内容")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "策略比较" }));
  expect(screen.getByText("统一策略比较内容")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test and verify RED**

Run `cd frontend && npm test -- --run src/pages/__tests__/PaperTradingTabs.test.tsx`.
Expected: module or button not found.

- [ ] **Step 3: Add API types and methods**

Mirror the snake_case backend contracts exactly and add:

```ts
createStrategyComparison: (body: StrategyComparisonCreate) =>
  request<StrategyComparisonRun>("/paper-trading/strategy-comparisons", {
    method: "POST",
    body: JSON.stringify(body),
  }),
getStrategyComparison: (runId: string) =>
  request<StrategyComparisonRun>(`/paper-trading/strategy-comparisons/${encodeURIComponent(runId)}`),
```

Use literal unions for run status, result status, strategy keys, and scorecard status. Do not use `any`.

- [ ] **Step 4: Add the Tab shell without moving existing state**

At the top of `PaperTrading`, add `const [tab, setTab] = useState<PaperTradingTab>("history")`. Render the page title `模拟盘`, then two buttons in the required order. Wrap the current body after the Tab bar in `{tab === "history" && <>...</>}` and render `<StrategyComparisonTab />` for the other branch. Do not move the current hooks or delete existing markup; React hooks must remain unconditional.

Create the initial focused component so the page compiles before Task 7:

```tsx
export function StrategyComparisonTab() {
  return <div className="rounded-xl border bg-card p-4 text-sm text-muted-foreground">策略比较准备中</div>;
}
```

- [ ] **Step 5: Verify and commit**

Run `cd frontend && npm test -- --run src/pages/__tests__/PaperTradingTabs.test.tsx`.

```bash
git add frontend/src/lib/api.ts frontend/src/pages/PaperTrading.tsx frontend/src/components/paper-trading/StrategyComparisonTab.tsx frontend/src/pages/__tests__/PaperTradingTabs.test.tsx
git commit -m "feat: add paper trading workspace tabs"
```

### Task 7: Build the strategy comparison form, polling, scorecard, and charts

**Files:**
- Modify: `frontend/src/components/paper-trading/StrategyComparisonTab.tsx`
- Create: `frontend/src/components/paper-trading/StrategyComparisonCharts.tsx`
- Create: `frontend/src/components/paper-trading/__tests__/StrategyComparisonTab.test.tsx`
- Create: `frontend/src/components/paper-trading/__tests__/StrategyComparisonCharts.test.tsx`

**Interfaces:**
- `StrategyComparisonTab` calls the Task 6 API and owns form/run/polling state.
- `StrategyComparisonCharts({ results })` consumes completed `StrategyComparisonResult[]` only.
- Produces helper `comparisonChartSeries(results, field)` for deterministic unit testing.

- [ ] **Step 1: Write failing form and result tests**

Freeze the clock, render the component, and assert defaults are five years ago/today, initial capital 100000, cost 20, short-window client validation, create/poll behavior, partial result rendering, persistent bias warning, and scorecard labels.

```tsx
it("defaults to a five-year comparison and renders honest partial results", async () => {
  vi.setSystemTime(new Date("2026-07-13T12:00:00Z"));
  apiMock.createStrategyComparison.mockResolvedValue({ ...queuedRun, run_id: "comparison-1" });
  apiMock.getStrategyComparison.mockResolvedValue(partialFixture);
  render(<StrategyComparisonTab />);
  expect(screen.getByLabelText("开始日期")).toHaveValue("2021-07-13");
  expect(screen.getByLabelText("结束日期")).toHaveValue("2026-07-13");
  await userEvent.click(screen.getByRole("button", { name: "运行统一比较" }));
  expect(await screen.findByText("SPY 买入持有")).toBeInTheDocument();
  expect(screen.getByText(/存在幸存者偏差/)).toBeInTheDocument();
  expect(screen.getByText(/Strategy V0 暂不可用/)).toBeInTheDocument();
});
```

For chart helpers, assert aligned labels and values for `normalized`, `drawdown`, and `cash_ratio` and omission of unavailable results.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd frontend && npm test -- --run src/components/paper-trading/__tests__/StrategyComparisonTab.test.tsx src/components/paper-trading/__tests__/StrategyComparisonCharts.test.tsx
```

- [ ] **Step 3: Implement comparison state and polling**

Use `date-fns`-free native helpers to subtract calendar years safely. Poll every 1,000 ms while status is `queued` or `running`, clear the timer on unmount, and keep the last result during Tab switches. Render shortcut buttons 1年/3年/5年/10年, labeled date inputs, capital and cost inputs, progress, errors, cache hit, and coverage.

Render six metric cards per completed strategy using the backend values only. Format returns and drawdowns as percentages, Sharpe/Calmar to two decimals, and never substitute unavailable values with zero.

Render the fixed warnings:

```tsx
{run.survivorship_bias && (
  <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700">
    Strategy V0 使用 {run.universe_source_date} 获取的当前 S&amp;P 500 成分股回测历史，存在幸存者偏差。结果仅用于策略结构筛选，不能作为实盘盈利证据。
  </div>
)}
<p className="text-xs text-muted-foreground">现金收益率按 0% 计算；所有收盘信号均在下一交易日开盘执行。</p>
```

- [ ] **Step 4: Implement shared ECharts comparisons**

Follow `PaperEquityChart.tsx`: initialize/dispose ECharts in `useEffect`, use `getChartTheme()` and `useDarkMode()`, disable animation, and create four panels:

- normalized net value (`normalized`)
- underwater drawdown (`drawdown * 100`)
- cash ratio (`cash_ratio * 100`)
- annual returns grouped by year (`metrics.annual_returns`)

The pure helper returns `{ name, data: [date, value][] }[]` so tests do not depend on canvas. Use stable colors per strategy across every chart.

- [ ] **Step 5: Verify component, page, and API tests**

Run:

```bash
cd frontend && npm test -- --run src/components/paper-trading/__tests__/StrategyComparisonTab.test.tsx src/components/paper-trading/__tests__/StrategyComparisonCharts.test.tsx src/pages/__tests__/PaperTradingTabs.test.tsx
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/paper-trading/StrategyComparisonTab.tsx frontend/src/components/paper-trading/StrategyComparisonCharts.tsx frontend/src/components/paper-trading/__tests__
git commit -m "feat: visualize paper strategy comparisons"
```

### Task 8: Run end-to-end verification and document the user-visible method

**Files:**
- Modify: `README.md`

**Interfaces:**
- No new runtime interfaces. Confirms all prior tasks compose correctly.

- [ ] **Step 1: Add concise README documentation**

Under the existing simulated-trading section, document the two Tabs, the three fixed strategies, five-year default, zero-cash-yield assumption, next-session execution, and current-constituent survivorship warning. Do not present comparison output as investment advice or a profit guarantee.

- [ ] **Step 2: Run full backend verification**

```bash
cd agent && ../.venv/bin/pytest -q
```

Expected: all backend tests pass; only documented existing deprecation warnings may remain.

- [ ] **Step 3: Run full frontend verification and production build**

```bash
cd frontend && npm test -- --run
npm run build
```

Expected: all frontend tests pass and Vite production build exits 0. The existing large chart chunk warning is non-blocking.

- [ ] **Step 4: Inspect the live local page**

Open `/paper-trading`, verify `历史回测` is selected first, run a cached or fixture-backed comparison, and capture screenshots of both Tabs. Confirm the bias warning, partial-state behavior, and all four chart panels are visually readable at desktop width.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md
git commit -m "docs: explain paper strategy comparison"
```
