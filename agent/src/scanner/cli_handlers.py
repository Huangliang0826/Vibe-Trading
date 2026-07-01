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
from src.scanner.tracking import (
    backfill_returns, calibration_check, load_all_tracking,
)

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

    track_p = sub.add_parser("track", help="backfill forward returns for a scan date")
    track_p.add_argument("--asof", required=True, help="scan date to track")
    track_p.add_argument("--json", action="store_true")

    cal_p = sub.add_parser("calibrate", help="check calibration across all tracked scans")
    cal_p.add_argument("--threshold", type=float, default=8.0, help="alert threshold in pp")
    cal_p.add_argument("--min-samples", type=int, default=100)


def _build_scan(universe: str, asof: str, top: int) -> ScanResult:
    """Load the manifest, build all providers, run the scan."""
    from src.factors.registry import Registry
    from src.scanner.providers.anomaly import AnomalyProvider
    from src.scanner.providers.event import EventProvider
    from src.scanner.providers.factor_rank import FactorRankProvider

    manifest_warning = None
    try:
        manifest = load_factor_manifest(universe=universe)
    except FileNotFoundError:
        manifest = {"factors": []}
        manifest_warning = "当前股票池尚无因子白名单，暂时仅使用异常与事件扫描"
    providers = [
        FactorRankProvider(manifest=manifest, registry=Registry(), top_n=top),
        AnomalyProvider(top_n=top),
        EventProvider(top_n=top),
    ]
    result = run_scan(universe=universe, asof=asof, providers=providers)
    if universe == "hstech":
        from src.scanner.universe_metadata import attach_company_names

        result = attach_company_names(result)
    if manifest_warning:
        result.warnings.insert(0, manifest_warning)
    return result


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
        if cmd == "track":
            from src.scanner.store import load_scan as _load_scan, default_root
            scan_path = default_root() / args.asof / "run.json"
            if not scan_path.is_file():
                print(f"no scan found for {args.asof}", file=sys.stderr)
                return 1
            result = _load_scan(scan_path)
            records = backfill_returns(args.asof, result.to_dict()["candidates"])
            if getattr(args, "json", False):
                print(json.dumps([r.to_dict() for r in records], indent=2))
            else:
                print(f"tracked {len(records)} symbols for {args.asof}")
                for r in records:
                    parts = [f"{r.symbol:<8} score={r.score:>5.1f}"]
                    if r.entry_price is not None:
                        parts.append(f"entry=${r.entry_price:.2f}")
                    for h, attr in [("1d", "fwd_1d"), ("5d", "fwd_5d"), ("20d", "fwd_20d")]:
                        val = getattr(r, attr)
                        if val is not None:
                            parts.append(f"{h}={val:+.2f}%")
                    print("  " + "  ".join(parts))
            return 0
        if cmd == "calibrate":
            all_records = load_all_tracking()
            if not all_records:
                print("no tracking data; run 'scan track' first", file=sys.stderr)
                return 1
            alerts = calibration_check(
                all_records,
                threshold_pp=args.threshold,
                min_samples=args.min_samples,
            )
            if not alerts:
                filled = [r for r in all_records if r.fwd_5d is not None]
                print(f"calibration OK ({len(filled)} samples tracked, "
                      f"threshold={args.threshold}pp)")
                return 0
            for a in alerts:
                print(f"  ⚠ {a.message}")
            return 2
        print("usage: vibe-trading scan {run,show,validate,track,calibrate}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
