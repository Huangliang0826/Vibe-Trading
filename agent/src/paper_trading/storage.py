"""SQLite + filesystem persistence for paper trading backtest runs."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from src.config.paths import get_runtime_root
from src.paper_trading.models import (
    PaperHolding,
    PaperTradingCreate,
    PaperTradingRun,
    PaperTradingStatus,
    ExperimentMetadata,
    StrategyConfig,
)

HKD_TO_USD = 1.0 / 7.8


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _code_version() -> str:
    """Resolve the source revision without making git a runtime requirement."""
    configured = os.getenv("VIBE_TRADING_CODE_VERSION", "").strip()
    if configured:
        return configured
    repo_root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _experiment_metadata(payload: PaperTradingCreate, total_usd: float) -> ExperimentMetadata:
    from backtest.costs import get_costs

    markets = sorted({holding.market for holding in payload.holdings})
    cost_model = {
        market: {
            "commission_bps": get_costs(market).commission_bps,
            "stamp_buy_bps": get_costs(market).stamp_buy_bps,
            "stamp_sell_bps": get_costs(market).stamp_sell_bps,
            "slippage_bps": get_costs(market).slippage_bps,
        }
        for market in markets
    }
    identity = {
        "code_version": _code_version(),
        "metric_version": "backtest.metrics.v2",
        "data_sources": ["yfinance"],
        "data_start": payload.start_date,
        "data_end": payload.end_date,
        "benchmark": "buy_and_hold",
        "holdings": [holding.model_dump(mode="json") for holding in payload.holdings],
        "strategy": payload.strategy.model_dump(mode="json"),
        "initial_usd": payload.initial_usd,
        "initial_hkd": payload.initial_hkd,
        "initial_total_usd": round(total_usd, 2),
        "cost_model": cost_model,
    }
    reproducibility_key = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ExperimentMetadata(
        code_version=identity["code_version"],
        metric_version=identity["metric_version"],
        data_sources=identity["data_sources"],
        data_start=payload.start_date,
        data_end=payload.end_date,
        benchmark="buy_and_hold",
        cost_model=cost_model,
        reproducibility_key=reproducibility_key,
    )


class PaperTradingStore:
    def __init__(self, root: Path | None = None, db_path: Path | None = None) -> None:
        runtime_root = get_runtime_root()
        self.root = root or (runtime_root / "paper_trading_runs")
        self.db_path = db_path or (runtime_root / "paper_trading.db")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits/rolls back and then always closes.

        A bare ``with self._connect()`` only manages the transaction, leaking
        the connection's file descriptors on every call.
        """
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._session() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS paper_runs (
                    run_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    strategy TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    initial_usd REAL NOT NULL,
                    initial_hkd REAL NOT NULL,
                    initial_total_usd REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT
                );
            """)

    def run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"paper-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", run_id):
            raise ValueError("invalid run_id")
        return self.root / run_id

    def create_run(self, payload: PaperTradingCreate) -> PaperTradingRun:
        now = _utc_now()
        run_id = f"paper-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        total_usd = payload.initial_usd + payload.initial_hkd * HKD_TO_USD

        run = PaperTradingRun(
            run_id=run_id,
            title=payload.title or f"{payload.strategy.name} backtest",
            holdings=payload.holdings,
            strategy=payload.strategy,
            start_date=payload.start_date,
            end_date=payload.end_date,
            initial_usd=payload.initial_usd,
            initial_hkd=payload.initial_hkd,
            initial_total_usd=round(total_usd, 2),
            status=PaperTradingStatus.queued,
            created_at=now,
            updated_at=now,
            experiment=_experiment_metadata(payload, total_usd),
        )

        path = self.run_dir(run_id)
        path.mkdir(parents=True, exist_ok=False)
        self._write_run(run)
        self._upsert_index(run)
        return run

    def get_run(self, run_id: str) -> PaperTradingRun | None:
        path = self.run_dir(run_id) / "run.json"
        if not path.exists():
            return None
        try:
            return PaperTradingRun.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def update_status(
        self,
        run_id: str,
        status: PaperTradingStatus,
        error: str | None = None,
    ) -> PaperTradingRun:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError("run not found")
        run.status = status
        run.updated_at = _utc_now()
        run.error = error
        self._write_run(run)
        self._upsert_index(run)
        return run

    def complete_run(
        self,
        run_id: str,
        metrics: dict,
        equity_curve: list[dict],
        trades: list[dict],
    ) -> PaperTradingRun:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError("run not found")
        run.status = PaperTradingStatus.completed
        run.updated_at = _utc_now()
        run.metrics = metrics
        run.equity_curve = equity_curve
        run.trades = trades
        self._write_run(run)
        self._upsert_index(run)
        return run

    def fail_run(self, run_id: str, error: str) -> PaperTradingRun:
        return self.update_status(run_id, PaperTradingStatus.failed, error=error)

    def list_runs(self, limit: int = 50) -> list[PaperTradingRun]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT run_id FROM paper_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        runs = []
        for row in rows:
            run = self.get_run(row["run_id"])
            if run is not None:
                runs.append(run)
        return runs

    def compare_runs(self, run_ids: list[str]) -> list[PaperTradingRun]:
        """Return selected runs in caller-provided order for experiment comparison."""
        result = []
        for run_id in run_ids:
            run = self.get_run(run_id)
            if run is not None:
                result.append(run)
        return result

    def delete_run(self, run_id: str) -> None:
        path = self.run_dir(run_id)
        if path.exists():
            shutil.rmtree(path)
        with self._session() as conn:
            conn.execute("DELETE FROM paper_runs WHERE run_id = ?", (run_id,))

    def _write_run(self, run: PaperTradingRun) -> None:
        path = self.run_dir(run.run_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "run.json").write_text(
            run.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def _upsert_index(self, run: PaperTradingRun) -> None:
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO paper_runs
                    (run_id, title, strategy, start_date, end_date,
                     initial_usd, initial_hkd, initial_total_usd,
                     status, created_at, updated_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    error = excluded.error
                """,
                (
                    run.run_id,
                    run.title,
                    run.strategy.name,
                    run.start_date,
                    run.end_date,
                    run.initial_usd,
                    run.initial_hkd,
                    run.initial_total_usd,
                    run.status.value,
                    run.created_at,
                    run.updated_at,
                    run.error,
                ),
            )
