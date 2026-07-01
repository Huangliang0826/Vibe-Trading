"""Persist per-universe scanner results with legacy-path compatibility."""
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
    day_dir = base / result.universe / result.asof
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


def _legacy_path(base: Path, asof: str, universe: str) -> Path | None:
    path = base / asof / "run.json"
    if not path.is_file():
        return None
    try:
        return path if load_scan(path).universe == universe else None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def list_scan_dates(universe: str = "sp500", root: Path | None = None) -> list[str]:
    """Return available scan dates (YYYY-MM-DD), most recent first."""
    base = Path(root) if root is not None else default_root()
    if not base.is_dir():
        return []
    dates = {
        d.name for d in (base / universe).iterdir()
        if d.is_dir() and (d / "run.json").is_file()
    } if (base / universe).is_dir() else set()
    dates.update(
        d.name for d in base.iterdir()
        if d.is_dir() and _legacy_path(base, d.name, universe) is not None
    )
    return sorted(dates, reverse=True)


def load_by_date(
    asof: str, universe: str = "sp500", root: Path | None = None,
) -> ScanResult | None:
    """Load a scan for a specific date, or None if not found."""
    base = Path(root) if root is not None else default_root()
    path = base / universe / asof / "run.json"
    if not path.is_file():
        path = _legacy_path(base, asof, universe)
    if path is None or not path.is_file():
        return None
    return load_scan(path)


def load_latest(universe: str = "sp500", root: Path | None = None) -> ScanResult | None:
    """Return the most recent scan by asof date, or None if none exist."""
    base = Path(root) if root is not None else default_root()
    if not base.is_dir():
        return None
    dates = list_scan_dates(universe, root=base)
    if not dates:
        return None
    return load_by_date(dates[0], universe, root=base)
