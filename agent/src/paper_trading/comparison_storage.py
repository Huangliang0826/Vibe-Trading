"""Filesystem persistence and deterministic caching for comparison runs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.config.paths import get_runtime_root
from src.paper_trading.comparison_models import (
    ComparisonStatus,
    STRATEGY_COMPARISON_VERSION,
    UNIVERSE_SOURCE_DATE,
    StrategyComparisonCreate,
    StrategyComparisonRun,
    utc_now,
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
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
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
        return self.save(StrategyComparisonRun(
            run_id=run_id, request=payload, created_at=now, updated_at=now, cache_key=key,
        ))

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
