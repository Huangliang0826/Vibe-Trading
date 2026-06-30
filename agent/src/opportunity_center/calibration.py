"""Forward-return calibration for historical opportunity snapshots."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Callable

import pandas as pd

from src.opportunity_center.models import Market, OpportunityItem, OpportunityOutcome
from src.opportunity_center.storage import OpportunityStore

CALIBRATION_VERSION = "forward-return-v1"
HORIZONS = (5, 20, 60)
PriceLoader = Callable[[str, str, str], pd.DataFrame]


class OpportunityCalibrationService:
    def __init__(
        self,
        store: OpportunityStore,
        *,
        price_loader: PriceLoader | None = None,
    ) -> None:
        self.store = store
        self.price_loader = price_loader or _load_price_history

    def refresh(self, as_of: date | None = None) -> int:
        cutoff = as_of or date.today()
        existing = {
            (row.market, row.code, row.snapshot_date, row.horizon_days)
            for row in self.store.list_outcomes()
            if row.status == "completed" and row.calibration_version == CALIBRATION_VERSION
        }
        candidates = _rank_candidates(self.store.list_snapshot_items())
        pending = [
            candidate for candidate in candidates
            if any((candidate.market, candidate.code, candidate.snapshot_date, horizon) not in existing for horizon in HORIZONS)
        ]
        if not pending:
            return 0

        cache: dict[str, pd.DataFrame] = {}

        def load(symbol: str, start_date: str) -> pd.DataFrame:
            if symbol not in cache:
                frame = self.price_loader(symbol, start_date, (cutoff + timedelta(days=1)).isoformat())
                normalized = _normalize_frame(frame)
                cache[symbol] = normalized.loc[normalized.index.date <= cutoff]
            return cache[symbol]

        writes = 0
        earliest = min(candidate.snapshot_date for candidate in pending)
        for candidate in pending:
            symbol = _symbol(candidate.market, candidate.code)
            benchmark_symbol = "^HSI" if candidate.market == "hk" else "^GSPC"
            outstanding = tuple(
                horizon for horizon in HORIZONS
                if (candidate.market, candidate.code, candidate.snapshot_date, horizon) not in existing
            )
            try:
                outcomes = compute_outcomes(
                    market=candidate.market,
                    code=candidate.code,
                    frame=load(symbol, earliest),
                    benchmark=load(benchmark_symbol, earliest),
                    snapshot_date=candidate.snapshot_date,
                    rank=candidate.rank,
                    is_top3=candidate.rank <= 3,
                    horizons=outstanding,
                )
            except Exception as exc:
                outcomes = [
                    _outcome(
                        candidate.market, candidate.code, candidate.snapshot_date,
                        horizon, candidate.rank, candidate.rank <= 3,
                        status="missing", error=str(exc),
                    )
                    for horizon in outstanding
                ]
            for outcome in outcomes:
                self.store.upsert_outcome(outcome)
                writes += 1
        return writes


class _RankedCandidate:
    def __init__(self, item: OpportunityItem, rank: int) -> None:
        self.market = item.market
        self.code = item.code
        self.snapshot_date = item.snapshot_date
        self.rank = rank


def _rank_candidates(items: list[OpportunityItem]) -> list[_RankedCandidate]:
    grouped: dict[str, list[OpportunityItem]] = defaultdict(list)
    for item in items:
        if item.score is not None and item.level != "数据不足":
            grouped[item.snapshot_date].append(item)
    ranked: list[_RankedCandidate] = []
    for snapshot_date, rows in grouped.items():
        rows.sort(key=lambda item: _ranking_key(item, snapshot_date))
        ranked.extend(_RankedCandidate(item, index) for index, item in enumerate(rows, start=1))
    return ranked


def _ranking_key(item: OpportunityItem, snapshot_date: str) -> tuple:
    signal = _parse_date(item.signal_date)
    snapshot = date.fromisoformat(snapshot_date)
    actionable = item.latest_action in {"entry", "add", "exit", "risk_exit"} and signal >= snapshot - timedelta(days=7)
    return (0 if actionable else 1, -signal.toordinal() if actionable else 0, -(item.score or -1), item.market, item.code)


def _parse_date(value: str | None) -> date:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return date.min


def _symbol(market: Market, code: str) -> str:
    if market == "hk":
        digits = "".join(character for character in code if character.isdigit())
        return f"{int(digits):04d}.HK"
    return code.upper()


def _load_price_history(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    from backtest.loaders.yfinance_loader import DataLoader as YFinanceLoader

    frame = YFinanceLoader().fetch([symbol], start_date, end_date, interval="1D").get(symbol)
    if frame is None or frame.empty:
        raise ValueError(f"No price data fetched for {symbol}")
    return frame


def compute_outcomes(
    *,
    market: Market,
    code: str,
    frame: pd.DataFrame,
    benchmark: pd.DataFrame,
    snapshot_date: str,
    rank: int,
    is_top3: bool,
    horizons: Iterable[int] = HORIZONS,
) -> list[OpportunityOutcome]:
    stock = _normalize_frame(frame)
    reference = _normalize_frame(benchmark)
    snapshot = date.fromisoformat(snapshot_date)
    future = stock.loc[stock.index.date > snapshot]
    requested = tuple(horizons)

    if future.empty:
        return [_outcome(market, code, snapshot_date, horizon, rank, is_top3) for horizon in requested]

    entry_date = future.index[0]
    entry_price = _price(future.iloc[0], "open")
    benchmark_entry = _price_on(reference, entry_date, "open")
    if entry_price is None:
        return [
            _outcome(market, code, snapshot_date, horizon, rank, is_top3, status="missing", error="stock entry price missing")
            for horizon in requested
        ]
    if benchmark_entry is None:
        return [
            _outcome(market, code, snapshot_date, horizon, rank, is_top3, status="missing", error="benchmark entry price missing")
            for horizon in requested
        ]

    results: list[OpportunityOutcome] = []
    for horizon in requested:
        base = {
            "entry_date": entry_date.date().isoformat(),
            "entry_price": entry_price,
        }
        if len(future) < horizon:
            results.append(_outcome(market, code, snapshot_date, horizon, rank, is_top3, **base))
            continue

        exit_date = future.index[horizon - 1]
        exit_price = _price(future.iloc[horizon - 1], "close")
        benchmark_exit = _price_on(reference, exit_date, "close")
        if exit_price is None:
            results.append(_outcome(
                market, code, snapshot_date, horizon, rank, is_top3,
                status="missing", error="stock exit price missing", **base,
            ))
            continue
        if benchmark_exit is None:
            results.append(_outcome(
                market, code, snapshot_date, horizon, rank, is_top3,
                status="missing", error="benchmark exit price missing",
                exit_date=exit_date.date().isoformat(), exit_price=exit_price, **base,
            ))
            continue

        stock_return = _return(entry_price, exit_price)
        benchmark_return = _return(benchmark_entry, benchmark_exit)
        results.append(_outcome(
            market, code, snapshot_date, horizon, rank, is_top3,
            status="completed", exit_date=exit_date.date().isoformat(), exit_price=exit_price,
            stock_return=stock_return, benchmark_return=benchmark_return,
            excess_return=round(stock_return - benchmark_return, 10), **base,
        ))
    return results


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    normalized.index = pd.DatetimeIndex(pd.to_datetime(normalized.index)).tz_localize(None)
    return normalized.sort_index().loc[~normalized.index.duplicated(keep="last")]


def _price(row: pd.Series, column: str) -> float | None:
    try:
        value = float(row[column])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _price_on(frame: pd.DataFrame, session: pd.Timestamp, column: str) -> float | None:
    if session not in frame.index:
        return None
    return _price(frame.loc[session], column)


def _return(entry: float, exit_: float) -> float:
    return round(exit_ / entry - 1.0, 10)


def _outcome(
    market: Market,
    code: str,
    snapshot_date: str,
    horizon: int,
    rank: int,
    is_top3: bool,
    **updates,
) -> OpportunityOutcome:
    status = updates.pop("status", "pending")
    return OpportunityOutcome(
        market=market,
        code=code,
        snapshot_date=snapshot_date,
        horizon_days=horizon,
        rank=rank,
        is_top3=is_top3,
        status=status,
        calibration_version=CALIBRATION_VERSION,
        **updates,
    )
