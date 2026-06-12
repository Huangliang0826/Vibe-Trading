"""CLI handlers for ``vibe-trading scan {run,show,validate}``.

Wired into the CLI by agent/cli/_legacy.py (mirrors src.factors.cli_handlers).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from src.scanner.core import ScanResult, run_scan
from src.scanner.manifest import build_factor_manifest, load_factor_manifest
from src.scanner.store import load_latest, save_scan

_DEFAULT_ZOOS = ["gtja191", "alpha101", "qlib158", "academic"]


def add_subparser(subparsers: Any) -> None:
    """Register the ``scan`` command group."""
    p = subparsers.add_parser("scan", help="US-equity opportunity scanner")
    sub = p.add_subparsers(dest="scan_cmd")

    run_p = sub.add_parser("run", help="run a scan for an as-of date")
    run_p.add_argument("--universe", default="sp500")
    run_p.add_argument("--asof", required=True, help="YYYY-MM-DD close date")
    run_p.add_argument("--top", type=int, default=20)
    run_p.add_argument("--json", action="store_true")

    show_p = sub.add_parser("show", help="show the most recent scan")
    show_p.add_argument("--json", action="store_true")

    val_p = sub.add_parser("validate", help="rebuild the factor whitelist")
    val_p.add_argument("--refresh-factors", action="store_true", dest="refresh_factors")
    val_p.add_argument("--universe", default="sp500")


def _build_scan(universe: str, asof: str, top: int) -> ScanResult:
    """Load the manifest, build the factor_rank provider, run the scan."""
    from src.factors.registry import Registry
    from src.scanner.providers.factor_rank import FactorRankProvider

    manifest = load_factor_manifest()
    provider = FactorRankProvider(manifest=manifest, registry=Registry(), top_n=top)
    return run_scan(universe=universe, asof=asof, providers=[provider])


def _print_result(result: ScanResult, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return
    print(f"scan {result.universe} @ {result.asof}  ({', '.join(result.providers)})")
    for i, c in enumerate(result.ranked(), start=1):
        print(f"{i:>3}  {c.symbol:<8} {c.score:>6.1f}  {c.attribution}")
    for w in result.warnings:
        print(f"  ! {w}", file=sys.stderr)


def dispatch(args: argparse.Namespace) -> int:
    """Execute a scan subcommand. Returns a process exit code."""
    cmd = getattr(args, "scan_cmd", None)
    try:
        if cmd == "run":
            result = _build_scan(args.universe, args.asof, args.top)
            save_scan(result)
            _print_result(result, getattr(args, "json", False))
            return 0
        if cmd == "show":
            result = load_latest()
            if result is None:
                print("no scans found; run 'vibe-trading scan run --asof ...'", file=sys.stderr)
                return 1
            _print_result(result, getattr(args, "json", False))
            return 0
        if cmd == "validate":
            if getattr(args, "refresh_factors", False):
                m = build_factor_manifest(
                    zoos=_DEFAULT_ZOOS, universe=args.universe, period="2018-2025")
                print(f"factor whitelist rebuilt: {len(m['factors'])} factors "
                      f"@ t>={m['threshold']}")
                return 0
            print("nothing to do; pass --refresh-factors", file=sys.stderr)
            return 1
        print("usage: vibe-trading scan {run,show,validate}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
