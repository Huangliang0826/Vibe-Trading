"""factor_rank: rank the cross-section by a whitelist of strict-bench factors."""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.scanner.core import Candidate
from src.scanner.providers.base import SignalProvider


def _asof_row(frame: pd.DataFrame, asof: str) -> pd.Series | None:
    """Last row at or before ``asof``; None if the frame has no such row."""
    if frame is None or frame.empty:
        return None
    idx = pd.to_datetime(frame.index)
    cutoff = pd.Timestamp(asof)
    mask = idx <= cutoff
    if not mask.any():
        return None
    return frame.loc[mask].iloc[-1]


class FactorRankProvider(SignalProvider):
    """Composite cross-sectional rank over whitelisted factors, weighted by |IR|."""

    provider_id = "factor_rank"

    def __init__(self, manifest: dict[str, Any], registry: Any, top_n: int = 20):
        self._factors = list(manifest.get("factors", []))
        self._registry = registry
        self._top_n = top_n

    def compute(self, panel: dict[str, pd.DataFrame], asof: str) -> list[Candidate]:
        if not self._factors:
            return []

        weighted = pd.Series(dtype=float)
        total_weight = 0.0
        contributions: dict[str, dict[str, float]] = {}

        for f in self._factors:
            ir = float(f.get("ir", 0.0))
            weight = abs(ir)
            if weight == 0.0:
                continue
            try:
                factor_df = self._registry.compute(f["id"], panel)
            except Exception:  # noqa: BLE001 — a broken factor must not sink the scan
                continue
            row = _asof_row(factor_df, asof)
            if row is None:
                continue
            row = row.dropna()
            if row.empty:
                continue
            # Percentile rank in [0,1]; sign(ir) flips negative-IR factors.
            pct = row.rank(pct=True)
            signed = pct if ir >= 0 else (1.0 - pct)
            contrib = signed * weight
            weighted = weighted.add(contrib, fill_value=0.0)
            total_weight += weight
            for sym, val in (contrib * 100.0).items():
                contributions.setdefault(str(sym), {})[str(f["id"])] = round(float(val), 2)

        if total_weight == 0.0 or weighted.empty:
            return []

        composite = (weighted / total_weight) * 100.0
        ranked = composite.sort_values(ascending=False)

        out: list[Candidate] = []
        for sym, score in ranked.head(self._top_n).items():
            detail = dict(sorted(
                contributions.get(str(sym), {}).items(),
                key=lambda kv: -kv[1],
            ))
            top_names = list(detail.keys())[:2]
            attribution = (
                "top by " + ", ".join(top_names) if top_names else "composite factor rank"
            )
            out.append(Candidate(
                symbol=str(sym),
                score=round(float(score), 2),
                provider_id=self.provider_id,
                attribution=attribution,
                detail=detail,
            ))
        return out
