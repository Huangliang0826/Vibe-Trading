#!/usr/bin/env python
"""Daily scan + tracking backfill entry point for launchd.

Usage: daily_scan.py [universe ...]
    universes to SCAN (default: hstech sp500); tracking backfill always
    covers all universes regardless of which were scanned.

Scheduled by ~/Library/LaunchAgents/com.vibetrading.scan-*.plist:
    17:10 local — hstech (after HK close)
    05:30 local — sp500 (after US close)
"""
from __future__ import annotations

import datetime as dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scanner.schedule import DEFAULT_UNIVERSES, run_daily  # noqa: E402


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    scan_universes = tuple(argv) or DEFAULT_UNIVERSES
    unknown = set(scan_universes) - set(DEFAULT_UNIVERSES)
    if unknown:
        print(f"unknown universe(s): {sorted(unknown)}", file=sys.stderr)
        return 2
    print(f"=== daily scan {dt.datetime.now():%Y-%m-%d %H:%M:%S} scan={scan_universes} ===")
    results = run_daily(scan_universes)
    for entry in results:
        print(entry)
    return 1 if any("error" in entry for entry in results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
