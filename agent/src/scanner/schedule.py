"""Daily scheduled scan + forward-return backfill.

Invoked by launchd via scripts/daily_scan.py, independent of the API
server, so scan history and tracking returns accumulate every trading
day even when nobody opens the web page.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

from src.scanner.store import list_scan_dates, load_by_date, save_scan
from src.scanner.tracking import backfill_returns, is_backfill_pending, load_tracking

log = logging.getLogger(__name__)

DEFAULT_UNIVERSES = ("hstech", "sp500")
DEFAULT_TOP = 20


def scan_universe(
    universe: str, top: int = DEFAULT_TOP, asof: str | None = None,
    scan_root: Path | None = None,
) -> str:
    """Run today's scan for ``universe`` and persist it. Returns the asof."""
    from src.scanner.cli_handlers import _build_scan

    asof = asof or dt.date.today().isoformat()
    result = _build_scan(universe, asof, top)
    save_scan(result, root=scan_root)
    log.info("scan %s %s: %d candidates", universe, result.asof, len(result.candidates))
    return result.asof


def backfill_universe(
    universe: str, scan_root: Path | None = None, tracking_root: Path | None = None,
) -> list[str]:
    """Backfill overdue forward returns for every stored scan date.

    Mirrors the /scan/tracking endpoint policy: create tracking records
    for dates that have none, refresh dates whose returns are due, and
    leave complete or beyond-retry dates alone. Returns processed dates.
    """
    processed: list[str] = []
    for date in list_scan_dates(universe=universe, root=scan_root):
        records = load_tracking(date, root=tracking_root, universe=universe)
        if records and not is_backfill_pending(records, date):
            continue
        stored = load_by_date(date, universe=universe, root=scan_root)
        if stored is None:
            continue
        backfill_returns(
            date,
            [candidate.to_dict() for candidate in stored.candidates],
            root=tracking_root,
            universe=universe,
        )
        processed.append(date)
    return processed


def refresh_news() -> dict[str, Any]:
    """Ingest the news-center RSS feeds so the digest is fresh without a manual
    click. Runs every day (news happens on weekends too)."""
    from src.news_center.service import NewsCenterService

    service = NewsCenterService()
    result = service.refresh()
    log.info("news refresh: fetched %d, total %d, latest %s",
             result.fetched, result.total, result.latest_date)
    if result.latest_date:
        try:
            digest = service.enrich_ai_digest(result.latest_date, language="zh")
            log.info("news direct web digest ready for %s via %s",
                     result.latest_date, digest.ai_model)
        except Exception as exc:  # noqa: BLE001 — RSS refresh remains successful
            log.warning("news fast AI digest unavailable for %s: %s", result.latest_date, exc)
    return {"fetched": result.fetched, "total": result.total,
            "latest_date": result.latest_date}


def run_daily(
    scan_universes: tuple[str, ...] | list[str],
    backfill_universes: tuple[str, ...] | list[str] = DEFAULT_UNIVERSES,
    top: int = DEFAULT_TOP,
) -> list[dict[str, Any]]:
    """Scan the given universes, backfill tracking, and refresh news.

    Failures are logged per section and never abort the rest of the run.
    """
    results: list[dict[str, Any]] = []
    if dt.date.today().weekday() >= 5:
        # Weekend: a scan would just relabel Friday's close under today's
        # date, polluting history. Backfill below still runs.
        log.info("weekend — skipping scans, running backfill only")
        scan_universes = ()
    for universe in scan_universes:
        entry: dict[str, Any] = {"universe": universe, "action": "scan"}
        try:
            entry["asof"] = scan_universe(universe, top)
        except Exception as exc:  # noqa: BLE001 — keep the batch going
            log.exception("daily scan failed for %s", universe)
            entry["error"] = str(exc)
        results.append(entry)
    for universe in backfill_universes:
        entry = {"universe": universe, "action": "backfill"}
        try:
            entry["dates"] = backfill_universe(universe)
        except Exception as exc:  # noqa: BLE001
            log.exception("backfill failed for %s", universe)
            entry["error"] = str(exc)
        results.append(entry)

    news_entry: dict[str, Any] = {"action": "news"}
    try:
        news_entry.update(refresh_news())
    except Exception as exc:  # noqa: BLE001
        log.exception("news refresh failed")
        news_entry["error"] = str(exc)
    results.append(news_entry)

    return results
