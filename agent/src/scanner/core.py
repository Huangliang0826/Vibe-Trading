"""Scanner core: data types and the run_scan orchestrator.

A single ``ScanResult`` is produced here and serialized once; CLI, REST, and the
agent tool all consume this same shape so no surface recomputes derived numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class Candidate:
    """One ranked opportunity. ``attribution`` is the human-readable 'why'."""

    symbol: str
    score: float
    provider_id: str
    attribution: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": round(float(self.score), 2),
            "provider_id": self.provider_id,
            "attribution": self.attribution,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Candidate":
        return cls(
            symbol=str(d["symbol"]),
            score=float(d["score"]),
            provider_id=str(d["provider_id"]),
            attribution=str(d["attribution"]),
            detail=dict(d.get("detail") or {}),
        )


@dataclass
class ScanResult:
    """A full scan run: context + ranked candidates + warnings."""

    universe: str
    asof: str
    providers: list[str]
    candidates: list[Candidate]
    warnings: list[str] = field(default_factory=list)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ScanResult):
            return NotImplemented
        return (
            self.universe == other.universe
            and self.asof == other.asof
            and self.providers == other.providers
            and sorted(self.candidates, key=lambda c: (-c.score, c.symbol))
            == sorted(other.candidates, key=lambda c: (-c.score, c.symbol))
            and self.warnings == other.warnings
        )

    def ranked(self) -> list[Candidate]:
        """Candidates sorted by score descending (ties broken by symbol)."""
        return sorted(self.candidates, key=lambda c: (-c.score, c.symbol))

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe": self.universe,
            "asof": self.asof,
            "providers": list(self.providers),
            "candidates": [c.to_dict() for c in self.ranked()],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScanResult":
        return cls(
            universe=str(d["universe"]),
            asof=str(d["asof"]),
            providers=[str(p) for p in d.get("providers", [])],
            candidates=[Candidate.from_dict(c) for c in d.get("candidates", [])],
            warnings=[str(w) for w in d.get("warnings", [])],
        )


def _truncate_panel(panel: dict[str, pd.DataFrame], asof: str) -> dict[str, Any]:
    """Return a copy of ``panel`` with every frame cut to rows <= asof.

    Structural look-ahead block: providers physically cannot read future rows.
    """
    cutoff = pd.Timestamp(asof)
    out: dict[str, Any] = {}
    for col, frame in panel.items():
        if frame is None or getattr(frame, "empty", True):
            out[col] = frame
            continue
        idx = pd.to_datetime(frame.index)
        out[col] = frame.loc[idx <= cutoff]
    return out


def run_scan(
    universe: str,
    asof: str,
    providers: list[Any],
    period: str = "2018-2025",
    panel_loader: Any = None,
) -> ScanResult:
    """Run all ``providers`` over the truncated universe panel as of ``asof``.

    Args:
        universe: Universe key (``sp500``).
        asof: ISO close date to scan.
        providers: Instantiated SignalProvider-likes (have .provider_id + .compute).
        period: History window passed to the panel loader.
        panel_loader: Injectable ``(universe, period) -> panel``; defaults to the
            real ``_load_universe_panel``.

    Returns:
        A ScanResult (NOT persisted — caller decides).
    """
    if panel_loader is None:
        from src.tools.alpha_bench_tool import _load_universe_panel as panel_loader  # type: ignore

    panel = panel_loader(universe, period)
    truncated = _truncate_panel(panel, asof)

    candidates: list[Candidate] = []
    used: list[str] = []
    warnings: list[str] = []
    for prov in providers:
        used.append(prov.provider_id)
        try:
            candidates.extend(prov.compute(truncated, asof))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"provider {prov.provider_id} failed: {exc}")

    return ScanResult(
        universe=universe, asof=asof, providers=used,
        candidates=candidates, warnings=warnings,
    )
