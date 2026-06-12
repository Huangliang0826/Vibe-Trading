"""Persist ScanResult to ~/.vibe-trading/scans/{asof}/run.json (fsync'd)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.scanner.core import ScanResult


def default_root() -> Path:
    return Path.home() / ".vibe-trading" / "scans"


def save_scan(result: ScanResult, root: Path | None = None) -> Path:
    """Write ``result`` to ``{root}/{asof}/run.json`` atomically; return the path."""
    base = Path(root) if root is not None else default_root()
    day_dir = base / result.asof
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "run.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    return path


def load_scan(path: Path) -> ScanResult:
    """Load one ``run.json`` into a ScanResult."""
    return ScanResult.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_latest(root: Path | None = None) -> ScanResult | None:
    """Return the most recent scan by asof date, or None if none exist."""
    base = Path(root) if root is not None else default_root()
    if not base.is_dir():
        return None
    runs = sorted(
        (d for d in base.iterdir() if d.is_dir() and (d / "run.json").is_file()),
        key=lambda d: d.name,
    )
    if not runs:
        return None
    return load_scan(runs[-1] / "run.json")
