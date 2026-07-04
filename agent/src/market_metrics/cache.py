"""Atomic disk cache for validated market-metric responses."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import FORMULA_VERSION
from .models import MarketMetricsResponse


def make_cache_key(market: str, symbol: str, period: str, adjustment: str) -> str:
    return ":".join((market.lower(), symbol.upper(), period.upper(), adjustment.lower()))


class MarketMetricsCache:
    def __init__(self, root: Path | None = None, *, formula_version: str = FORMULA_VERSION):
        self.root = root or Path.home() / ".vibe-trading" / "market_metrics"
        self.formula_version = formula_version

    def path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / digest[:2] / f"{digest}.json"

    def get(self, key: str, *, source_revision: str) -> MarketMetricsResponse | None:
        path = self.path_for(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("formula_version") != self.formula_version:
                return None
            if payload.get("source_revision") != source_revision:
                return None
            return MarketMetricsResponse.from_dict(payload["response"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def put(
        self,
        key: str,
        response: MarketMetricsResponse,
        *,
        source_revision: str,
    ) -> bool:
        if response.data_status.quality == "invalid":
            return False
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = {
            "formula_version": self.formula_version,
            "source_revision": source_revision,
            "response": response.to_dict(),
        }
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(path)
            return True
        except (OSError, TypeError, ValueError):
            tmp.unlink(missing_ok=True)
            return False
