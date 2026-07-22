"""Ten-week DCA backtesting and auditable virtual portfolio tracking."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import numpy as np
import pandas as pd

from src.asset_management.portfolio_models import (
    AnnualReturn,
    EquityPoint,
    ManualAllocation,
    PortfolioBacktestRequest,
    PortfolioBacktestResult,
    PortfolioDefinition,
    TrackerPosition,
    TrackingPortfolio,
)
from src.config.paths import get_runtime_root
from src.paper_trading.models import PaperHolding
from src.paper_trading.strategies import _to_code


MONEY = Decimal("0.00000001")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_EVEN)


def _currency(market: str) -> str:
    return {"hk": "HKD", "cn": "CNY"}.get(market, "USD")


def _code(item: ManualAllocation) -> str:
    return _to_code(PaperHolding(symbol=item.symbol, market=item.market, allocation_pct=1.0))


def _history_loader(codes: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    from backtest.loaders.yfinance_loader import DataLoader

    return DataLoader().fetch(codes, start, end, interval="1D")


def _usd_price_frames(
    allocations: list[ManualAllocation], start: str, end: str, loader=_history_loader,
) -> tuple[dict[tuple[str, str], pd.Series], list[str]]:
    risky = [item for item in allocations if item.market != "cash"]
    codes = [_code(item) for item in risky]
    markets = {item.market for item in risky}
    fx_codes = (["HKD=X"] if "hk" in markets else []) + (["CNY=X"] if "cn" in markets else [])
    fetched = loader(codes + fx_codes, start, end)
    fx: dict[str, pd.Series] = {}
    for market, fx_code in (("hk", "HKD=X"), ("cn", "CNY=X")):
        frame = fetched.get(fx_code)
        if frame is not None and not frame.empty and "close" in frame:
            fx[market] = pd.to_numeric(frame["close"], errors="coerce").dropna().sort_index()
    result: dict[tuple[str, str], pd.Series] = {}
    warnings: list[str] = []
    for item, code in zip(risky, codes):
        frame = fetched.get(code)
        if frame is None or frame.empty or "close" not in frame:
            raise ValueError(f"无法取得 {item.symbol} 的历史价格")
        native = pd.to_numeric(frame["close"], errors="coerce").dropna().sort_index()
        native.index = pd.to_datetime(native.index).tz_localize(None)
        if item.market in {"hk", "cn"}:
            rate = fx.get(item.market)
            if rate is None or rate.empty:
                raise ValueError(f"无法取得 {_currency(item.market)}/USD 历史汇率")
            rate.index = pd.to_datetime(rate.index).tz_localize(None)
            aligned = rate.reindex(native.index).ffill().bfill()
            native = native / aligned
        result[(item.market, item.symbol.upper())] = native
    return result, warnings


def _native_price_frames(
    allocations: list[ManualAllocation], start: str, end: str, loader=_history_loader,
) -> dict[tuple[str, str], tuple[pd.Series, pd.Series]]:
    """Return native close and native-to-USD FX series for auditable tracking."""
    risky = [item for item in allocations if item.market != "cash"]
    codes = [_code(item) for item in risky]
    markets = {item.market for item in risky}
    fx_codes = (["HKD=X"] if "hk" in markets else []) + (["CNY=X"] if "cn" in markets else [])
    fetched = loader(codes + fx_codes, start, end)
    fx_native_per_usd: dict[str, pd.Series] = {}
    for market, fx_code in (("hk", "HKD=X"), ("cn", "CNY=X")):
        frame = fetched.get(fx_code)
        if frame is not None and not frame.empty and "close" in frame:
            series = pd.to_numeric(frame["close"], errors="coerce").dropna().sort_index()
            series.index = pd.to_datetime(series.index).tz_localize(None)
            fx_native_per_usd[market] = series
    result: dict[tuple[str, str], tuple[pd.Series, pd.Series]] = {}
    for item, code in zip(risky, codes):
        frame = fetched.get(code)
        if frame is None or frame.empty or "close" not in frame:
            raise ValueError(f"无法取得 {item.symbol} 的价格")
        native = pd.to_numeric(frame["close"], errors="coerce").dropna().sort_index()
        native.index = pd.to_datetime(native.index).tz_localize(None)
        if item.market in {"hk", "cn"}:
            rate = fx_native_per_usd.get(item.market)
            if rate is None or rate.empty:
                raise ValueError(f"无法取得 {_currency(item.market)}/USD 汇率")
            fx_to_usd = (1.0 / rate.reindex(native.index).ffill().bfill()).astype(float)
        else:
            fx_to_usd = pd.Series(1.0, index=native.index)
        result[(item.market, item.symbol.upper())] = (native, fx_to_usd)
    return result


class PortfolioBacktestService:
    def __init__(self, loader=_history_loader) -> None:
        self.loader = loader

    def run(self, request: PortfolioBacktestRequest) -> PortfolioBacktestResult:
        end = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        start = end - pd.DateOffset(years=request.years)
        prices, warnings = _usd_price_frames(
            request.allocations, start.date().isoformat(), end.date().isoformat(), self.loader,
        )
        warnings.append("建仓与季度再平衡按当日收盘价模拟，暂未计入佣金、税费和滑点。")
        raw_frame = pd.concat(prices, axis=1).sort_index()
        common_trading_index = raw_frame.dropna().index
        frame = raw_frame.ffill().dropna()
        if len(frame) < 126:
            raise ValueError("共同历史数据不足半年")
        if common_trading_index.empty:
            raise ValueError("所选资产没有共同可交易日期")
        weights = {(item.market, item.symbol.upper()): item.weight for item in request.allocations if item.market != "cash"}
        cash_weight = next(item.weight for item in request.allocations if item.market == "cash")
        quantities = {key: 0.0 for key in prices}
        cash = request.initial_capital
        installment_dates: list[pd.Timestamp] = []
        for number in range(request.installments):
            scheduled = common_trading_index[0] + pd.Timedelta(days=number * request.interval_days)
            matches = common_trading_index[common_trading_index >= scheduled]
            if len(matches):
                installment_dates.append(matches[0])
        schedule_map: dict[pd.Timestamp, list[int]] = {}
        for number, scheduled in enumerate(installment_dates):
            schedule_map.setdefault(scheduled, []).append(number)

        if not installment_dates:
            raise ValueError("回测区间内没有可执行的建仓日期")
        investment_completed = installment_dates[-1]
        rebalance_dates: list[pd.Timestamp] = []
        rebalance_number = 1
        while True:
            scheduled = investment_completed + pd.DateOffset(
                months=request.rebalance_months * rebalance_number,
            )
            matches = common_trading_index[common_trading_index >= scheduled]
            if not len(matches):
                break
            executed = matches[0]
            if not rebalance_dates or executed != rebalance_dates[-1]:
                rebalance_dates.append(executed)
            rebalance_number += 1
        rebalance_set = set(rebalance_dates)

        values: list[float] = []
        for timestamp, row in frame.iterrows():
            for _ in schedule_map.get(timestamp, []):
                for key, weight in weights.items():
                    amount = request.initial_capital * weight / request.installments
                    quantities[key] += amount / float(row[key])
                    cash -= amount
            if timestamp in rebalance_set:
                portfolio_value = cash + sum(
                    quantities[key] * float(row[key]) for key in quantities
                )
                for key, weight in weights.items():
                    quantities[key] = portfolio_value * weight / float(row[key])
                cash = portfolio_value * cash_weight
            values.append(cash + sum(quantities[key] * float(row[key]) for key in quantities))
        series = pd.Series(values, index=frame.index)
        daily = series.pct_change().fillna(0.0)
        running_max = series.cummax()
        max_drawdown = float((series / running_max - 1.0).min())
        elapsed_years = max((series.index[-1] - series.index[0]).days / 365.25, 1 / 365.25)
        total_return = float(series.iloc[-1] / request.initial_capital - 1.0)
        cagr = float((series.iloc[-1] / request.initial_capital) ** (1 / elapsed_years) - 1.0)
        annual_returns: list[AnnualReturn] = []
        for year, group in series.groupby(series.index.year):
            baseline = request.initial_capital if year == series.index[0].year else float(series[series.index.year < year].iloc[-1])
            annual_returns.append(AnnualReturn(year=int(year), return_rate=float(group.iloc[-1] / baseline - 1.0)))
        annual_average_return = float(np.mean([item.return_rate for item in annual_returns]))
        curve = [EquityPoint(date=index.date().isoformat(), value=float(value), cumulative_return=float(value / request.initial_capital - 1.0)) for index, value in series.items()]
        return PortfolioBacktestResult(
            start_date=series.index[0].date().isoformat(), end_date=series.index[-1].date().isoformat(),
            initial_capital=request.initial_capital, final_value=float(series.iloc[-1]),
            total_profit=float(series.iloc[-1] - request.initial_capital), total_return=total_return,
            cagr=cagr, annual_average_return=annual_average_return, max_drawdown=max_drawdown,
            annual_volatility=float(daily.std() * np.sqrt(252)),
            installments=len(installment_dates),
            investment_completed_date=investment_completed.date().isoformat(),
            rebalances=len(rebalance_dates),
            rebalance_dates=[timestamp.date().isoformat() for timestamp in rebalance_dates],
            annual_returns=annual_returns, curve=curve, warnings=warnings,
        )


class TrackingStore:
    def __init__(self, path: Path | None = None, loader=_history_loader) -> None:
        self.path = path or (get_runtime_root() / "asset_management" / "tracking.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.loader = loader
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init(self) -> None:
        with self._session() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trackers (
                    tracker_id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    initial_capital TEXT NOT NULL, installments INTEGER NOT NULL, interval_days INTEGER NOT NULL,
                    start_date TEXT NOT NULL, schema_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS targets (
                    tracker_id TEXT NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL, name TEXT NOT NULL,
                    asset_type TEXT NOT NULL, weight TEXT NOT NULL,
                    PRIMARY KEY (tracker_id, market, symbol), FOREIGN KEY (tracker_id) REFERENCES trackers(tracker_id)
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY, tracker_id TEXT NOT NULL, tranche INTEGER NOT NULL,
                    market TEXT NOT NULL, symbol TEXT NOT NULL, executed_at TEXT NOT NULL,
                    amount_usd TEXT NOT NULL, price_native TEXT NOT NULL, fx_to_usd TEXT NOT NULL, quantity TEXT NOT NULL,
                    UNIQUE (tracker_id, tranche, market, symbol), FOREIGN KEY (tracker_id) REFERENCES trackers(tracker_id)
                );
                CREATE TABLE IF NOT EXISTS cash_ledger (
                    entry_id TEXT PRIMARY KEY, tracker_id TEXT NOT NULL, event_type TEXT NOT NULL,
                    reference_id TEXT NOT NULL UNIQUE, amount_usd TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    FOREIGN KEY (tracker_id) REFERENCES trackers(tracker_id)
                );
                CREATE TABLE IF NOT EXISTS rebalance_runs (
                    run_id TEXT PRIMARY KEY, tracker_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    scheduled_date TEXT NOT NULL, executed_at TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE (tracker_id, sequence), FOREIGN KEY (tracker_id) REFERENCES trackers(tracker_id)
                );
                CREATE TABLE IF NOT EXISTS rebalance_transactions (
                    transaction_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tracker_id TEXT NOT NULL,
                    market TEXT NOT NULL, symbol TEXT NOT NULL, executed_at TEXT NOT NULL,
                    trade_value_usd TEXT NOT NULL, price_native TEXT NOT NULL,
                    fx_to_usd TEXT NOT NULL, quantity TEXT NOT NULL,
                    UNIQUE (run_id, market, symbol),
                    FOREIGN KEY (run_id) REFERENCES rebalance_runs(run_id),
                    FOREIGN KEY (tracker_id) REFERENCES trackers(tracker_id)
                );
                CREATE TABLE IF NOT EXISTS valuations (
                    tracker_id TEXT NOT NULL, valuation_date TEXT NOT NULL, created_at TEXT NOT NULL,
                    total_value TEXT NOT NULL, cash_value TEXT NOT NULL,
                    PRIMARY KEY (tracker_id, valuation_date), FOREIGN KEY (tracker_id) REFERENCES trackers(tracker_id)
                );
            """)

    def create(self, definition: PortfolioDefinition) -> TrackingPortfolio:
        tracker_id = f"portfolio-{uuid4().hex[:12]}"
        created_at = _now()
        with self._session() as conn:
            conn.execute(
                "INSERT INTO trackers VALUES (?, 'building', ?, ?, ?, ?, ?, 'tracking.v2')",
                (tracker_id, created_at, str(_decimal(definition.initial_capital)), definition.installments, definition.interval_days, date.today().isoformat()),
            )
            conn.executemany(
                "INSERT INTO targets VALUES (?, ?, ?, ?, ?, ?)",
                [(tracker_id, item.market, item.symbol.upper(), item.name or item.symbol, item.asset_type, str(_decimal(item.weight))) for item in definition.allocations],
            )
            conn.execute(
                "INSERT INTO cash_ledger VALUES (?, ?, 'initial_deposit', ?, ?, ?)",
                (
                    f"cash-{uuid4().hex}",
                    tracker_id,
                    f"deposit-{tracker_id}",
                    str(_decimal(definition.initial_capital)),
                    created_at,
                ),
            )
        return self.refresh(tracker_id)

    def latest(self) -> TrackingPortfolio | None:
        with self._session() as conn:
            row = conn.execute("SELECT tracker_id FROM trackers ORDER BY created_at DESC LIMIT 1").fetchone()
        return self.refresh(row["tracker_id"]) if row else None

    def refresh(self, tracker_id: str) -> TrackingPortfolio:
        with self._session() as conn:
            tracker = conn.execute("SELECT * FROM trackers WHERE tracker_id = ?", (tracker_id,)).fetchone()
            if not tracker:
                raise ValueError("tracking portfolio not found")
            target_rows = conn.execute("SELECT * FROM targets WHERE tracker_id = ? ORDER BY rowid", (tracker_id,)).fetchall()
        allocations = [ManualAllocation(symbol=row["symbol"], market=row["market"], name=row["name"], asset_type=row["asset_type"], weight=float(row["weight"])) for row in target_rows]
        start_date = date.fromisoformat(tracker["start_date"])
        today = date.today()
        # Include prior sessions so a portfolio created on a weekend/holiday can still be valued.
        load_start = start_date - timedelta(days=30)
        market_prices = _native_price_frames(
            allocations, load_start.isoformat(), today.isoformat(), self.loader,
        )
        prices = {key: native * fx for key, (native, fx) in market_prices.items()}
        warnings: list[str] = []
        risky = [item for item in allocations if item.market != "cash"]
        capital = Decimal(tracker["initial_capital"])
        installments = int(tracker["installments"])
        interval_days = int(tracker["interval_days"])
        due = min(installments, max(0, (today - start_date).days // interval_days + 1))
        common_trading_index: pd.DatetimeIndex | None = None
        for native, _ in market_prices.values():
            common_trading_index = (
                native.index
                if common_trading_index is None
                else common_trading_index.intersection(native.index)
            )
        if common_trading_index is None or common_trading_index.empty:
            raise ValueError("所选资产没有共同可交易日期")

        with self._session() as conn:
            for tranche in range(1, due + 1):
                scheduled = pd.Timestamp(start_date + timedelta(days=(tranche - 1) * interval_days))
                for item in risky:
                    key = (item.market, item.symbol.upper())
                    series = prices[key]
                    candidates = series.index[series.index >= scheduled]
                    if not len(candidates):
                        continue
                    executed = candidates[0]
                    native_series, fx_series = market_prices[key]
                    native_price = _decimal(native_series.loc[executed])
                    fx_to_usd = _decimal(fx_series.loc[executed])
                    usd_price = (native_price * fx_to_usd).quantize(MONEY)
                    amount = (capital * _decimal(item.weight) / Decimal(installments)).quantize(MONEY)
                    quantity = (amount / usd_price).quantize(MONEY)
                    transaction_id = f"tx-{tracker_id}-{tranche}-{item.market}-{item.symbol.upper()}"
                    conn.execute(
                        "INSERT OR IGNORE INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (transaction_id, tracker_id, tranche, item.market, item.symbol.upper(), executed.date().isoformat(), str(amount), str(native_price), str(fx_to_usd), str(quantity)),
                    )
            tx_rows = conn.execute("SELECT * FROM transactions WHERE tracker_id = ?", (tracker_id,)).fetchall()

            # Backfill the ledger as well, so databases created by tracking.v1 remain auditable.
            conn.execute(
                "INSERT OR IGNORE INTO cash_ledger VALUES (?, ?, 'initial_deposit', ?, ?, ?)",
                (
                    f"cash-{uuid4().hex}", tracker_id, f"deposit-{tracker_id}",
                    str(capital), tracker["created_at"],
                ),
            )
            for row in tx_rows:
                conn.execute(
                    "INSERT OR IGNORE INTO cash_ledger VALUES (?, ?, 'buy', ?, ?, ?)",
                    (
                        f"cash-{uuid4().hex}", tracker_id, row["transaction_id"],
                        str(-Decimal(row["amount_usd"])), row["executed_at"],
                    ),
                )

            transaction_counts: dict[int, int] = {}
            for row in tx_rows:
                transaction_counts[int(row["tranche"])] = transaction_counts.get(int(row["tranche"]), 0) + 1
            completed = 0
            for tranche in range(1, installments + 1):
                if transaction_counts.get(tranche, 0) != len(risky):
                    break
                completed = tranche

            investment_completed_day: str | None = None
            if completed >= installments:
                final_rows = [row for row in tx_rows if int(row["tranche"]) == installments]
                investment_completed_day = max(str(row["executed_at"]) for row in final_rows)
                sequence = 1
                while True:
                    scheduled = pd.Timestamp(investment_completed_day) + pd.DateOffset(months=3 * sequence)
                    candidates = common_trading_index[
                        (common_trading_index >= scheduled)
                        & (common_trading_index.date <= today)
                    ]
                    if not len(candidates):
                        break
                    executed = candidates[0]
                    executed_day = executed.date().isoformat()
                    run_id = f"rebalance-{tracker_id}-{sequence}"
                    existing = conn.execute(
                        "SELECT run_id FROM rebalance_runs WHERE tracker_id = ? AND sequence = ?",
                        (tracker_id, sequence),
                    ).fetchone()
                    if existing is None:
                        prior_rebalance_rows = conn.execute(
                            "SELECT * FROM rebalance_transactions WHERE tracker_id = ?",
                            (tracker_id,),
                        ).fetchall()
                        ledger_before = conn.execute(
                            "SELECT amount_usd, occurred_at FROM cash_ledger WHERE tracker_id = ?",
                            (tracker_id,),
                        ).fetchall()
                        cash_before = sum(
                            (
                                Decimal(row["amount_usd"])
                                for row in ledger_before
                                if str(row["occurred_at"])[:10] <= executed_day
                            ),
                            Decimal("0"),
                        )
                        quantities_before: dict[tuple[str, str], Decimal] = {}
                        portfolio_value = cash_before
                        for item in risky:
                            key = (item.market, item.symbol.upper())
                            dca_quantity = sum(
                                (
                                    Decimal(row["quantity"])
                                    for row in tx_rows
                                    if row["market"] == item.market
                                    and row["symbol"] == item.symbol.upper()
                                    and row["executed_at"] <= executed_day
                                ),
                                Decimal("0"),
                            )
                            rebalance_quantity = sum(
                                (
                                    Decimal(row["quantity"])
                                    for row in prior_rebalance_rows
                                    if row["market"] == item.market
                                    and row["symbol"] == item.symbol.upper()
                                    and row["executed_at"] <= executed_day
                                ),
                                Decimal("0"),
                            )
                            quantity = dca_quantity + rebalance_quantity
                            quantities_before[key] = quantity
                            native_series, fx_series = market_prices[key]
                            usd_price = (
                                _decimal(native_series.loc[executed])
                                * _decimal(fx_series.loc[executed])
                            ).quantize(MONEY)
                            portfolio_value += quantity * usd_price

                        conn.execute(
                            "INSERT INTO rebalance_runs VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                run_id, tracker_id, sequence, scheduled.date().isoformat(),
                                executed_day, _now(),
                            ),
                        )
                        for item in risky:
                            key = (item.market, item.symbol.upper())
                            native_series, fx_series = market_prices[key]
                            native_price = _decimal(native_series.loc[executed])
                            fx_to_usd = _decimal(fx_series.loc[executed])
                            usd_price = (native_price * fx_to_usd).quantize(MONEY)
                            current_value = quantities_before[key] * usd_price
                            target_value = (portfolio_value * _decimal(item.weight)).quantize(MONEY)
                            trade_value = (target_value - current_value).quantize(MONEY)
                            quantity = (trade_value / usd_price).quantize(MONEY)
                            transaction_id = f"rebalance-tx-{tracker_id}-{sequence}-{item.market}-{item.symbol.upper()}"
                            conn.execute(
                                "INSERT INTO rebalance_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (
                                    transaction_id, run_id, tracker_id, item.market,
                                    item.symbol.upper(), executed_day, str(trade_value),
                                    str(native_price), str(fx_to_usd), str(quantity),
                                ),
                            )
                            conn.execute(
                                "INSERT INTO cash_ledger VALUES (?, ?, 'rebalance', ?, ?, ?)",
                                (
                                    f"cash-{uuid4().hex}", tracker_id, transaction_id,
                                    str(-trade_value), executed_day,
                                ),
                            )
                    sequence += 1

            rebalance_tx_rows = conn.execute(
                "SELECT * FROM rebalance_transactions WHERE tracker_id = ?",
                (tracker_id,),
            ).fetchall()
            rebalance_run_rows = conn.execute(
                "SELECT * FROM rebalance_runs WHERE tracker_id = ? ORDER BY sequence",
                (tracker_id,),
            ).fetchall()
            ledger_rows = conn.execute(
                "SELECT amount_usd, occurred_at FROM cash_ledger WHERE tracker_id = ?",
                (tracker_id,),
            ).fetchall()

        cash_value = sum((Decimal(row["amount_usd"]) for row in ledger_rows), Decimal("0"))
        latest_date = max(series.index[-1] for series in prices.values())
        positions: list[TrackerPosition] = []
        total_positions = Decimal("0")
        for item in risky:
            rows = [row for row in tx_rows if row["market"] == item.market and row["symbol"] == item.symbol.upper()]
            rebalance_rows = [
                row for row in rebalance_tx_rows
                if row["market"] == item.market and row["symbol"] == item.symbol.upper()
            ]
            quantity = sum((Decimal(row["quantity"]) for row in rows), Decimal("0")) + sum(
                (Decimal(row["quantity"]) for row in rebalance_rows), Decimal("0")
            )
            key = (item.market, item.symbol.upper())
            native_series, fx_series = market_prices[key]
            native_price = _decimal(native_series.iloc[-1])
            fx_to_usd = _decimal(fx_series.iloc[-1])
            usd_price = (native_price * fx_to_usd).quantize(MONEY)
            value = (quantity * usd_price).quantize(MONEY)
            total_positions += value
            positions.append(TrackerPosition(
                symbol=item.symbol.upper(), market=item.market, name=item.name or item.symbol,
                target_weight=item.weight, quantity=float(quantity), price_native=float(native_price),
                currency=_currency(item.market), fx_to_usd=float(fx_to_usd), value_usd=float(value), actual_weight=0.0,
                price_date=native_series.index[-1].date().isoformat(),
            ))
            if native_series.index[-1].date() < today:
                warnings.append(
                    f"{item.symbol.upper()} 使用最近交易日 {native_series.index[-1].date().isoformat()} 收盘价估值。"
                )
        total = cash_value + total_positions
        for position in positions:
            position.actual_weight = position.value_usd / float(total) if total else 0.0
        valuation_date = latest_date.date().isoformat()
        with self._session() as conn:
            existing_dates = {
                row["valuation_date"]
                for row in conn.execute(
                    "SELECT valuation_date FROM valuations WHERE tracker_id = ?", (tracker_id,)
                ).fetchall()
            }
            valuation_dates = sorted({
                timestamp.normalize()
                for series in prices.values()
                for timestamp in series.index
                if start_date <= timestamp.date() <= latest_date.date()
            })
            for timestamp in valuation_dates:
                day = timestamp.date().isoformat()
                if day in existing_dates and day != valuation_date:
                    continue
                cash_on_day = sum(
                    (
                        Decimal(row["amount_usd"])
                        for row in ledger_rows
                        if str(row["occurred_at"])[:10] <= day
                    ),
                    Decimal("0"),
                )
                position_value = Decimal("0")
                for item in risky:
                    key = (item.market, item.symbol.upper())
                    quantity_on_day = sum(
                        (
                            Decimal(row["quantity"])
                            for row in tx_rows
                            if row["market"] == item.market
                            and row["symbol"] == item.symbol.upper()
                            and row["executed_at"] <= day
                        ),
                        Decimal("0"),
                    ) + sum(
                        (
                            Decimal(row["quantity"])
                            for row in rebalance_tx_rows
                            if row["market"] == item.market
                            and row["symbol"] == item.symbol.upper()
                            and row["executed_at"] <= day
                        ),
                        Decimal("0"),
                    )
                    available_prices = prices[key].loc[:timestamp]
                    if not available_prices.empty:
                        position_value += quantity_on_day * _decimal(available_prices.iloc[-1])
                value_on_day = (cash_on_day + position_value).quantize(MONEY)
                conn.execute(
                    "INSERT OR REPLACE INTO valuations VALUES (?, ?, ?, ?, ?)",
                    (tracker_id, day, _now(), str(value_on_day), str(cash_on_day)),
                )
            valuation_rows = conn.execute("SELECT * FROM valuations WHERE tracker_id = ? ORDER BY valuation_date", (tracker_id,)).fetchall()
            status = "active" if completed >= installments else "building"
            conn.execute("UPDATE trackers SET status = ? WHERE tracker_id = ?", (status, tracker_id))
        next_date = start_date + timedelta(days=completed * interval_days) if completed < installments else None
        completed_rebalances = len(rebalance_run_rows)
        last_rebalance_date = (
            str(rebalance_run_rows[-1]["executed_at"]) if rebalance_run_rows else None
        )
        next_rebalance_date = None
        if investment_completed_day is not None:
            warnings.append("季度再平衡按共同交易日收盘价模拟，暂未计入佣金、税费和滑点。")
            next_rebalance_date = (
                pd.Timestamp(investment_completed_day)
                + pd.DateOffset(months=3 * (completed_rebalances + 1))
            ).date().isoformat()
        cash_target = next(item.weight for item in allocations if item.market == "cash")
        strategic_cash = total * _decimal(cash_target)
        deployment_cash = max(cash_value - strategic_cash, Decimal("0"))
        previous = float(valuation_rows[-2]["total_value"]) if len(valuation_rows) > 1 else float(capital)
        curve = [EquityPoint(date=row["valuation_date"], value=float(row["total_value"]), cumulative_return=float(Decimal(row["total_value"]) / capital - 1)) for row in valuation_rows]
        return TrackingPortfolio(
            tracker_id=tracker_id, status=status, created_at=tracker["created_at"], initial_capital=float(capital),
            current_value=float(total), cumulative_return=float(total / capital - 1), today_return=float(total / _decimal(previous) - 1),
            completed_installments=completed, total_installments=installments,
            next_installment_date=next_date.isoformat() if next_date else None,
            investment_completed_date=investment_completed_day,
            completed_rebalances=completed_rebalances,
            last_rebalance_date=last_rebalance_date,
            next_rebalance_date=next_rebalance_date,
            strategic_cash=float(strategic_cash), deployment_cash=float(deployment_cash), positions=positions,
            curve=curve, last_updated=_now(), warnings=warnings,
        )
