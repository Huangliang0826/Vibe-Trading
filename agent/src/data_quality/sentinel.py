"""Daily data-quality sentinel for the shared market-data feeds.

The scanner, backtests, and forecasts all consume the same yfinance feed
(``backtest.loaders.yfinance_loader`` downloads with ``auto_adjust=True``).
If that feed silently degrades — unapplied splits, missing trading days,
inconsistent adjustment baselines — every downstream conclusion drifts with
no alarm. This module fetches the *raw* series (``auto_adjust=False``, so
both ``Close`` and ``Adj Close`` are visible) for every watchlist symbol and
runs five checks:

  1. staleness        — last bar too old (feed stopped updating)
  2. calendar gaps    — missing stretches of business days mid-series
  3. price jumps      — unadjusted-split artifacts / suspicious extreme moves
  4. adj/close ratio  — adjustment baseline off (latest ratio must be ≈ 1),
                        ratio above 1 (rare outside reverse splits), or
                        adjustment churn (ratio stepping on too many days)
  5. bad values       — non-positive or missing closes in the recent window

Findings are written in detail to ``~/.vibe-trading/logs/data_quality.log``
and each ALERT is mirrored as one line into the existing watchdog log
(``~/.vibe-trading/watchdog.log``) so problems surface in the file that is
already being watched.

Run manually::

    cd agent && PYTHONPATH=. ../.venv/bin/python -m src.data_quality.sentinel

Scheduled daily via ``com.vibetrading.data-quality`` (launchd, 22:20 local,
before the 22:35 backup job).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

# ── Tunables ─────────────────────────────────────────────────────────────────
STALE_MAX_BDAYS = 4          # HK long holidays run ~3 business days
GAP_MAX_BDAYS = 8            # CN Golden Week / Spring Festival close 6-7
                             # business days — only longer holes are anomalies
SPLIT_CLOSE_JUMP = 0.30      # raw close jumps this much...
SPLIT_ADJ_QUIET = 0.10       # ...while adj close moves less → unapplied split
EXTREME_ADJ_MOVE = 0.45      # adjusted move this large → bad tick or crash
RATIO_LATEST_TOL = 0.015     # latest adj/close must sit within 1 ± this
RATIO_ABOVE_ONE = 1.05       # adj above close beyond rounding (reverse splits excepted)
RATIO_CHURN_STEPS = 15       # ratio step-days beyond this in the window → churn
RATIO_STEP_MIN = 0.001       # a ratio move counts as a step above 0.1%
RECENT_ROWS = 30             # window for bad-value scan
HISTORY_DAYS = 400           # calendar days of history to examine
SOURCE_DOWN_FRACTION = 0.5   # >½ of symbols empty → one source-level alert

WATCHDOG_LOG = Path.home() / ".vibe-trading" / "watchdog.log"
DETAIL_LOG = Path.home() / ".vibe-trading" / "logs" / "data_quality.log"
LOG_CAP_BYTES = 262144       # same convention as the watchdog script


@dataclass(frozen=True)
class Finding:
    symbol: str
    check: str
    severity: str  # "ALERT" | "WARN"
    detail: str

    def line(self) -> str:
        return f"{self.severity} [{self.check}] {self.symbol}: {self.detail}"


# ── Pure checks (unit-tested; no I/O) ────────────────────────────────────────

def check_staleness(
    frame: pd.DataFrame, asof: pd.Timestamp, max_lag_bdays: int = STALE_MAX_BDAYS,
) -> list[Finding]:
    symbol = str(frame.attrs.get("symbol", "?"))
    if frame.empty:
        return [Finding(symbol, "staleness", "ALERT", "series is empty")]
    last = pd.Timestamp(frame.index.max()).tz_localize(None).normalize()
    lag = int(np.busday_count(last.date(), pd.Timestamp(asof).normalize().date()))
    if lag > max_lag_bdays:
        return [Finding(
            symbol, "staleness", "ALERT",
            f"last bar {last.date()} is {lag} business days old (max {max_lag_bdays})",
        )]
    return []


def check_gaps(frame: pd.DataFrame, max_gap_bdays: int = GAP_MAX_BDAYS) -> list[Finding]:
    symbol = str(frame.attrs.get("symbol", "?"))
    if len(frame) < 2:
        return []
    dates = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    out: list[Finding] = []
    prev = dates[0]
    for current in dates[1:]:
        gap = int(np.busday_count(prev.date(), current.date())) - 1
        if gap > max_gap_bdays:
            out.append(Finding(
                symbol, "calendar_gap", "ALERT",
                f"{gap} business days missing between {prev.date()} and {current.date()}",
            ))
        prev = current
    return out


def check_price_jumps(frame: pd.DataFrame) -> list[Finding]:
    symbol = str(frame.attrs.get("symbol", "?"))
    if len(frame) < 2 or "close" not in frame or "adj_close" not in frame:
        return []
    close_ret = frame["close"].pct_change()
    adj_ret = frame["adj_close"].pct_change()
    out: list[Finding] = []
    # Unapplied corporate action: the raw close jumps while adjusted is quiet.
    artifact = (close_ret.abs() > SPLIT_CLOSE_JUMP) & (adj_ret.abs() < SPLIT_ADJ_QUIET)
    for ts in frame.index[artifact.fillna(False)]:
        out.append(Finding(
            symbol, "split_artifact", "ALERT",
            f"{pd.Timestamp(ts).date()}: raw close moved "
            f"{close_ret.loc[ts]:+.1%} while adj close moved {adj_ret.loc[ts]:+.1%} "
            "— unadjusted corporate action in the raw series",
        ))
    # Extreme adjusted moves: bad tick or a real crash — either way, eyeball it.
    extreme = adj_ret.abs() > EXTREME_ADJ_MOVE
    for ts in frame.index[extreme.fillna(False)]:
        out.append(Finding(
            symbol, "extreme_move", "WARN",
            f"{pd.Timestamp(ts).date()}: adjusted move {adj_ret.loc[ts]:+.1%}",
        ))
    return out


def check_adj_ratio(frame: pd.DataFrame) -> list[Finding]:
    symbol = str(frame.attrs.get("symbol", "?"))
    if frame.empty or "close" not in frame or "adj_close" not in frame:
        return []
    valid = frame[(frame["close"] > 0) & frame["adj_close"].notna()]
    if valid.empty:
        return []
    ratio = valid["adj_close"] / valid["close"]
    out: list[Finding] = []
    latest = float(ratio.iloc[-1])
    # yfinance back-adjusts: on the most recent bar adj must equal close.
    if abs(latest - 1.0) > RATIO_LATEST_TOL:
        out.append(Finding(
            symbol, "adj_baseline", "ALERT",
            f"latest adj/close ratio {latest:.4f} deviates from 1 — "
            "adjustment baseline is off; modules may disagree on prices",
        ))
    above = ratio[ratio > RATIO_ABOVE_ONE]
    if not above.empty:
        out.append(Finding(
            symbol, "adj_above_close", "WARN",
            f"adj close exceeds close on {len(above)} day(s) "
            f"(max ratio {float(above.max()):.3f}) — reverse split or bad data",
        ))
    steps = int((ratio.pct_change().abs() > RATIO_STEP_MIN).sum())
    if steps > RATIO_CHURN_STEPS:
        out.append(Finding(
            symbol, "adj_churn", "ALERT",
            f"adj/close ratio stepped on {steps} days in the window "
            f"(max {RATIO_CHURN_STEPS}) — adjustment factors are unstable",
        ))
    return out


def check_bad_values(frame: pd.DataFrame, recent_rows: int = RECENT_ROWS) -> list[Finding]:
    symbol = str(frame.attrs.get("symbol", "?"))
    if frame.empty or "close" not in frame:
        return []
    recent = frame.tail(recent_rows)
    bad = int(((recent["close"] <= 0) | recent["close"].isna()).sum())
    if bad:
        return [Finding(
            symbol, "bad_values", "ALERT",
            f"{bad} non-positive/missing close(s) in the last {len(recent)} rows",
        )]
    return []


def run_symbol_checks(frame: pd.DataFrame, asof: pd.Timestamp) -> list[Finding]:
    return [
        *check_staleness(frame, asof),
        *check_gaps(frame),
        *check_price_jumps(frame),
        *check_adj_ratio(frame),
        *check_bad_values(frame),
    ]


# ── Symbol collection + raw fetch ────────────────────────────────────────────

def watchlist_yahoo_symbols() -> list[str]:
    """All watchlist codes across markets, as yfinance symbols."""
    from src.paper_trading.hstech_best import normalize_best_strategy_symbol
    from src.watchlist import WatchlistStore

    store = WatchlistStore()
    symbols: list[str] = []
    for market in ("hk", "us", "cn"):
        for code in store.get(market):
            try:
                _, yahoo_symbol, _ = normalize_best_strategy_symbol(code, market)
            except ValueError:
                symbols.append(code)  # let the fetch surface it as empty
                continue
            # normalize returns the internal loader format; US uses a ".US"
            # suffix there, but yfinance itself wants the bare ticker.
            if market == "us":
                yahoo_symbol = yahoo_symbol.removesuffix(".US")
            symbols.append(yahoo_symbol)
    return sorted(set(symbols))


def fetch_raw_frames(symbols: list[str], asof: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Raw (non-auto-adjusted) history so close and adj close both exist."""
    import yfinance as yf

    start = (asof - pd.Timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    raw = yf.download(
        symbols, start=start, end=(asof + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        interval="1d", auto_adjust=False, progress=False, group_by="ticker",
    )
    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            sub = raw[symbol] if isinstance(raw.columns, pd.MultiIndex) else raw
            frame = pd.DataFrame({
                "close": sub["Close"], "adj_close": sub["Adj Close"],
            }).dropna(how="all")
        except Exception:
            frame = pd.DataFrame()
        frame.attrs["symbol"] = symbol
        frames[symbol] = frame
    return frames


# ── Reporting ────────────────────────────────────────────────────────────────

def _cap_log(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > LOG_CAP_BYTES:
            data = path.read_bytes()[-LOG_CAP_BYTES // 2:]
            path.write_bytes(data)
    except OSError:
        pass


def _append(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _cap_log(path)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(f"{stamp} {line}\n")


def main(argv: list[str] | None = None) -> int:
    asof = pd.Timestamp(os.environ.get("VIBE_DQ_ASOF") or pd.Timestamp.today().normalize())
    symbols = watchlist_yahoo_symbols()
    if not symbols:
        _append(DETAIL_LOG, ["OK: watchlist empty — nothing to check"])
        return 0

    frames = fetch_raw_frames(symbols, asof)
    empty = [s for s, f in frames.items() if f.empty]

    findings: list[Finding] = []
    if len(empty) > len(symbols) * SOURCE_DOWN_FRACTION:
        # Feed-level outage: one alert instead of one per symbol.
        findings.append(Finding(
            "yfinance", "source_down", "ALERT",
            f"{len(empty)}/{len(symbols)} symbols returned no data — feed outage?",
        ))
        checked = [s for s in symbols if s not in empty]
    else:
        checked = symbols
        for symbol in empty:
            findings.append(Finding(symbol, "staleness", "ALERT", "series is empty"))

    for symbol in checked:
        if not frames[symbol].empty:
            findings.extend(run_symbol_checks(frames[symbol], asof))

    alerts = [f for f in findings if f.severity == "ALERT"]
    warns = [f for f in findings if f.severity == "WARN"]

    summary = (
        f"data-quality: {len(symbols)} symbols checked as of {asof.date()} — "
        f"{len(alerts)} alert(s), {len(warns)} warning(s)"
    )
    _append(DETAIL_LOG, [summary, *(f.line() for f in findings)] if findings else [f"OK: {summary}"])
    if alerts:
        _append(WATCHDOG_LOG, [f"data-quality {f.line()}" for f in alerts])

    print(summary)
    for f in findings:
        print(" ", f.line())
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
