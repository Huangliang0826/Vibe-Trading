from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from src.scanner.tracking import TrackingRecord, load_all_tracking

from .models import AnalyticsEvent
from .quality_adapters import (
    BacktestQualityAdapter,
    PaperTradingQualityAdapter,
    ScannerQualityAdapter,
)

SourceStatus = Literal["available", "partial", "no_data", "source_unavailable", "error"]

_HORIZON_MATURITY_DAYS = {
    "fwd_1d": 2,
    "fwd_5d": 8,
    "fwd_10d": 15,
    "fwd_20d": 28,
}


@dataclass(frozen=True)
class QualitySourceResult:
    source: str
    status: SourceStatus
    events: list[AnalyticsEvent]
    records_scanned: int
    data_through: str | None
    coverage_days: int
    reason: str | None = None


def _result(
    source: str,
    events: list[AnalyticsEvent],
    records_scanned: int,
    *,
    errors: int = 0,
) -> QualitySourceResult:
    days = sorted({event.metadata["as_of"] for event in events})
    if errors:
        status: SourceStatus = "partial" if events else "error"
        reason = "parse_errors"
    elif events:
        status = "available"
        reason = None
    else:
        status = "no_data"
        reason = "no_local_records"
    return QualitySourceResult(
        source=source,
        status=status,
        events=events,
        records_scanned=records_scanned,
        data_through=days[-1] if days else None,
        coverage_days=len(days),
        reason=reason,
    )


class ScannerHistorySource:
    source = "scanner"

    def __init__(self, root: Path, *, universes: tuple[str, ...] = ("sp500", "hstech")) -> None:
        self.root = Path(root)
        self.universes = universes

    def read(self, start: date, end: date) -> QualitySourceResult:
        if not self.root.is_dir():
            return _result(self.source, [], 0)
        adapter = ScannerQualityAdapter()
        events: list[AnalyticsEvent] = []
        records_scanned = 0
        errors = 0
        for universe in self.universes:
            try:
                records = load_all_tracking(root=self.root, universe=universe)
            except (OSError, ValueError, json.JSONDecodeError):
                errors += 1
                continue
            records_scanned += len(records)
            market = {"sp500": "us", "hstech": "hk"}.get(universe, universe)
            cursor = start
            while cursor <= end:
                matured: list[TrackingRecord] = []
                for record in records:
                    try:
                        signal_day = date.fromisoformat(record.asof)
                    except ValueError:
                        errors += 1
                        continue
                    if signal_day > cursor:
                        continue
                    updates = {
                        field: getattr(record, field)
                        if signal_day + timedelta(days=pad) <= cursor
                        else None
                        for field, pad in _HORIZON_MATURITY_DAYS.items()
                    }
                    matured.append(replace(record, **updates))
                if matured:
                    events.extend(adapter.from_records(
                        matured,
                        market=market,
                        subject_id="all",
                        as_of=cursor,
                    ))
                cursor += timedelta(days=1)
        return _result(self.source, events, records_scanned, errors=errors)


def _observation_date(state: dict[str, Any], path: Path) -> date:
    for key in ("completed_at", "updated_at", "created_at"):
        value = state.get(key)
        if value:
            return date.fromisoformat(str(value)[:10])
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date()


def _numeric_metrics(path: Path) -> dict[str, float]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle), None)
    if not row:
        raise ValueError("metrics row missing")
    metrics: dict[str, float] = {}
    for key, raw in row.items():
        if not key or raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            metrics[key] = value
    if not metrics:
        raise ValueError("numeric metrics missing")
    return metrics


def _market_from_run(path: Path) -> str:
    for filename in ("req.json", "run_context.json"):
        try:
            payload = json.loads((path / filename).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        market = payload.get("market")
        if isinstance(market, str) and market:
            return market.lower()
        markets = payload.get("markets")
        if isinstance(markets, list):
            normalized = {str(item).lower() for item in markets if item}
            if len(normalized) == 1:
                return next(iter(normalized))
            if normalized:
                return "multi"
    return "unknown"


class BacktestHistorySource:
    source = "backtest"

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = Path(runs_dir)

    def read(self, start: date, end: date) -> QualitySourceResult:
        if not self.runs_dir.is_dir():
            return _result(self.source, [], 0)
        events: list[AnalyticsEvent] = []
        records_scanned = 0
        errors = 0
        adapter = BacktestQualityAdapter()
        for run_dir in sorted(path for path in self.runs_dir.iterdir() if path.is_dir()):
            records_scanned += 1
            try:
                state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
                if str(state.get("status", "")).lower() != "success":
                    continue
                as_of = _observation_date(state, run_dir)
                if as_of < start or as_of > end:
                    continue
                metrics = _numeric_metrics(run_dir / "artifacts" / "metrics.csv")
                events.extend(adapter.from_metrics(
                    run_id=run_dir.name,
                    market=_market_from_run(run_dir),
                    as_of=as_of,
                    metrics=metrics,
                ))
            except (OSError, ValueError, json.JSONDecodeError, StopIteration):
                errors += 1
        return _result(self.source, events, records_scanned, errors=errors)


class PaperTradingHistorySource:
    source = "paper_trading"

    def __init__(self, store: Any) -> None:
        self.store = store

    def read(self, start: date, end: date) -> QualitySourceResult:
        try:
            runs = self.store.list_runs(limit=500)
        except (OSError, ValueError):
            return QualitySourceResult(
                source=self.source,
                status="error",
                events=[],
                records_scanned=0,
                data_through=None,
                coverage_days=0,
                reason="source_read_failed",
            )
        events: list[AnalyticsEvent] = []
        errors = 0
        adapter = PaperTradingQualityAdapter()
        for run in runs:
            status = getattr(run, "status", "")
            status_value = getattr(status, "value", status)
            if status_value != "completed":
                continue
            try:
                as_of = date.fromisoformat(str(run.updated_at)[:10])
                if start <= as_of <= end:
                    events.extend(adapter.from_run(run))
            except (AttributeError, TypeError, ValueError):
                errors += 1
        return _result(self.source, events, len(runs), errors=errors)
