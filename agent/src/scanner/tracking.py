"""Forward-return tracking for scanner recommendations.

Convention: signal computed on T close, hypothetical entry at T+1 open.
We backfill actual forward returns (1d, 5d, 20d) so the scanner can
self-prove (or self-disprove) its accuracy over time.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


@dataclass
class TrackingRecord:
    symbol: str
    score: float
    asof: str  # signal date (T close)
    entry_date: str | None = None  # T+1
    entry_price: float | None = None  # T+1 open
    fwd_1d: float | None = None
    fwd_5d: float | None = None
    fwd_20d: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TrackingRecord:
        return cls(
            symbol=str(d["symbol"]),
            score=float(d["score"]),
            asof=str(d["asof"]),
            entry_date=d.get("entry_date"),
            entry_price=d.get("entry_price"),
            fwd_1d=d.get("fwd_1d"),
            fwd_5d=d.get("fwd_5d"),
            fwd_20d=d.get("fwd_20d"),
        )


def _default_tracking_root() -> Path:
    return Path.home() / ".vibe-trading" / "tracking"


def save_tracking(
    records: list[TrackingRecord], asof: str, root: Path | None = None,
    universe: str = "sp500",
) -> Path:
    base = (root or _default_tracking_root()) / universe / asof
    base.mkdir(parents=True, exist_ok=True)
    path = base / "tracking.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in records], f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    return path


def load_tracking(
    asof: str, root: Path | None = None, universe: str = "sp500",
) -> list[TrackingRecord]:
    base = root or _default_tracking_root()
    path = base / universe / asof / "tracking.json"
    if not path.is_file() and universe == "sp500":
        path = base / asof / "tracking.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [TrackingRecord.from_dict(d) for d in data]


def load_all_tracking(
    root: Path | None = None, universe: str = "sp500",
) -> list[TrackingRecord]:
    base = root or _default_tracking_root()
    if not base.is_dir():
        return []
    records: list[TrackingRecord] = []
    universe_root = base / universe
    if universe_root.is_dir():
        for day_dir in sorted(universe_root.iterdir()):
            if day_dir.is_dir() and (day_dir / "tracking.json").is_file():
                records.extend(load_tracking(day_dir.name, root, universe))
    if universe != "sp500":
        return records
    for day_dir in sorted(base.iterdir()):
        if day_dir.is_dir() and (day_dir / "tracking.json").is_file():
            records.extend(load_tracking(day_dir.name, root, universe))
    return records


def _strip_suffix(symbol: str) -> str:
    """Remove exchange suffix (e.g. '.US') for yfinance compatibility."""
    return symbol.rsplit(".", 1)[0] if "." in symbol else symbol


def _fetch_prices(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """Fetch adjusted OHLC for symbols over [start, end]."""
    if not symbols:
        return pd.DataFrame()
    yf_syms = [_strip_suffix(s) for s in symbols]
    df = yf.download(yf_syms, start=start, end=end,
                     auto_adjust=True, progress=False)
    if df.empty:
        return df
    if len(yf_syms) > 1:
        remap = {yf_s: orig for yf_s, orig in zip(yf_syms, symbols)}
        df = df.rename(columns=remap, level=1)
    return df


def backfill_returns(
    asof: str,
    candidates: list[dict[str, Any]],
    root: Path | None = None,
    price_fetcher: Any = None,
    universe: str = "sp500",
) -> list[TrackingRecord]:
    """Create/update tracking records with forward returns for a scan date.

    Args:
        asof: Signal date (T).
        candidates: List of candidate dicts from ScanResult.to_dict()["candidates"].
        root: Tracking storage root.
        price_fetcher: Injectable ``(symbols, start, end) -> DataFrame``;
            defaults to yfinance.

    Returns:
        Updated tracking records.
    """
    if not candidates:
        return []

    fetch = price_fetcher or _fetch_prices
    symbols = [c["symbol"] for c in candidates]

    # Fetch enough history: T+1 through T+30 (business days, pad for weekends)
    asof_ts = pd.Timestamp(asof)
    start = (asof_ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    end = (asof_ts + pd.Timedelta(days=45)).strftime("%Y-%m-%d")

    prices = fetch(symbols, start, end)

    existing = {r.symbol: r for r in load_tracking(asof, root, universe)}
    records: list[TrackingRecord] = []

    for c in candidates:
        sym = c["symbol"]
        rec = existing.get(sym, TrackingRecord(
            symbol=sym, score=c["score"], asof=asof,
        ))

        if prices.empty:
            records.append(rec)
            continue

        try:
            if len(symbols) == 1:
                sym_open = prices["Open"] if "Open" in prices.columns else None
                sym_close = prices["Close"] if "Close" in prices.columns else None
            else:
                sym_open = prices["Open"][sym] if "Open" in prices.columns.get_level_values(0) else None
                sym_close = prices["Close"][sym] if "Close" in prices.columns.get_level_values(0) else None
        except (KeyError, TypeError):
            records.append(rec)
            continue

        if sym_open is None or sym_close is None or sym_open.empty:
            records.append(rec)
            continue

        sym_open = sym_open.dropna()
        sym_close = sym_close.dropna()

        if len(sym_open) == 0:
            records.append(rec)
            continue

        # T+1 open = entry price
        entry_price = float(sym_open.iloc[0])
        entry_date = str(sym_open.index[0].date())
        rec = TrackingRecord(
            symbol=sym, score=c["score"], asof=asof,
            entry_date=entry_date, entry_price=entry_price,
        )

        if entry_price <= 0:
            records.append(rec)
            continue

        # Forward returns: close on T+N relative to entry
        for horizon, attr in [(1, "fwd_1d"), (5, "fwd_5d"), (20, "fwd_20d")]:
            if len(sym_close) > horizon:
                exit_price = float(sym_close.iloc[horizon])
                setattr(rec, attr, round((exit_price / entry_price - 1) * 100, 4))

        records.append(rec)

    save_tracking(records, asof, root, universe)
    return records


@dataclass
class CalibrationAlert:
    metric: str
    predicted_mean: float
    actual_mean: float
    divergence_pp: float
    n_samples: int
    message: str


def calibration_check(
    records: list[TrackingRecord],
    threshold_pp: float = 8.0,
    min_samples: int = 100,
) -> list[CalibrationAlert]:
    """Compare scanner scores vs actual forward returns.

    Returns alerts when the divergence exceeds ``threshold_pp`` percentage points
    at ``min_samples`` or more observations.
    """
    filled = [r for r in records if r.fwd_5d is not None and r.entry_price is not None]
    if len(filled) < min_samples:
        return []

    scores = pd.Series([r.score for r in filled])
    actuals = pd.Series([r.fwd_5d for r in filled])

    # Normalise scores to same scale as returns for comparison:
    # top-quintile vs bottom-quintile spread
    q80 = scores.quantile(0.8)
    q20 = scores.quantile(0.2)
    top_mask = scores >= q80
    bot_mask = scores <= q20

    if top_mask.sum() < 5 or bot_mask.sum() < 5:
        return []

    top_actual = float(actuals[top_mask].mean())
    bot_actual = float(actuals[bot_mask].mean())
    spread = top_actual - bot_actual

    alerts: list[CalibrationAlert] = []

    # If top-ranked stocks don't outperform bottom-ranked ones, something's wrong
    if spread < -threshold_pp:
        alerts.append(CalibrationAlert(
            metric="quintile_spread_5d",
            predicted_mean=float(scores[top_mask].mean()),
            actual_mean=top_actual,
            divergence_pp=round(spread, 2),
            n_samples=len(filled),
            message=(
                f"Top-quintile 5d return ({top_actual:+.2f}%) lags bottom-quintile "
                f"({bot_actual:+.2f}%) by {abs(spread):.1f}pp over {len(filled)} samples — "
                f"factor ranking may be inverted or stale"
            ),
        ))

    # Overall: if mean return of all recommended stocks is deeply negative
    overall_mean = float(actuals.mean())
    if overall_mean < -threshold_pp:
        alerts.append(CalibrationAlert(
            metric="overall_mean_5d",
            predicted_mean=float(scores.mean()),
            actual_mean=overall_mean,
            divergence_pp=round(overall_mean, 2),
            n_samples=len(filled),
            message=(
                f"Mean 5d forward return across all tracked picks is {overall_mean:+.2f}% "
                f"over {len(filled)} samples — scanner may be systematically wrong"
            ),
        ))

    return alerts
