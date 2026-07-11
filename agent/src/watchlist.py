"""SQLite-backed watchlist persistence."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from src.config.paths import get_runtime_root


def today_iso() -> str:
    return date.today().isoformat()


class WatchlistStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (get_runtime_root() / "watchlist.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits/rolls back and then always closes.

        A bare ``with self._connect()`` only manages the transaction, leaking
        the connection's file descriptors on every call.
        """
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._session() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    market TEXT NOT NULL,
                    code TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (market, code)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS watchlist_snapshots (
                    market TEXT NOT NULL,
                    effective_date TEXT NOT NULL,
                    codes_json TEXT NOT NULL,
                    PRIMARY KEY (market, effective_date)
                )
            """)
            for market in ("cn", "hk", "us"):
                has_history = conn.execute(
                    "SELECT 1 FROM watchlist_snapshots WHERE market = ? LIMIT 1", (market,)
                ).fetchone()
                codes = [row["code"] for row in conn.execute(
                    "SELECT code FROM watchlist WHERE market = ? ORDER BY sort_order", (market,)
                ).fetchall()]
                if codes and has_history is None:
                    self._save_snapshot(conn, market, codes)

    def get(self, market: str) -> list[str]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT code FROM watchlist WHERE market = ? ORDER BY sort_order",
                (market,),
            ).fetchall()
        return [row["code"] for row in rows]

    def set(self, market: str, codes: list[str]) -> list[str]:
        with self._session() as conn:
            conn.execute("DELETE FROM watchlist WHERE market = ?", (market,))
            for i, code in enumerate(codes):
                conn.execute(
                    "INSERT OR REPLACE INTO watchlist (market, code, sort_order) VALUES (?, ?, ?)",
                    (market, code.upper(), i),
                )
            normalized = [code.upper() for code in codes]
            self._save_snapshot(conn, market, normalized)
        return normalized

    def add(self, market: str, code: str) -> list[str]:
        code = code.upper()
        with self._session() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) as m FROM watchlist WHERE market = ?",
                (market,),
            ).fetchone()["m"]
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (market, code, sort_order) VALUES (?, ?, ?)",
                (market, code, max_order + 1),
            )
            codes = [row["code"] for row in conn.execute(
                "SELECT code FROM watchlist WHERE market = ? ORDER BY sort_order", (market,)
            ).fetchall()]
            self._save_snapshot(conn, market, codes)
        return codes

    def remove(self, market: str, code: str) -> list[str]:
        with self._session() as conn:
            conn.execute(
                "DELETE FROM watchlist WHERE market = ? AND code = ?",
                (market, code.upper()),
            )
            codes = [row["code"] for row in conn.execute(
                "SELECT code FROM watchlist WHERE market = ? ORDER BY sort_order", (market,)
            ).fetchall()]
            self._save_snapshot(conn, market, codes)
        return codes

    def get_as_of(self, market: str, as_of: str) -> list[str]:
        with self._session() as conn:
            row = conn.execute(
                """SELECT codes_json FROM watchlist_snapshots
                   WHERE market = ? AND effective_date <= ?
                   ORDER BY effective_date DESC LIMIT 1""",
                (market, as_of),
            ).fetchone()
        return list(json.loads(row["codes_json"])) if row is not None else []

    @staticmethod
    def _save_snapshot(conn: sqlite3.Connection, market: str, codes: list[str]) -> None:
        conn.execute(
            """INSERT INTO watchlist_snapshots (market, effective_date, codes_json)
               VALUES (?, ?, ?)
               ON CONFLICT(market, effective_date) DO UPDATE SET codes_json = excluded.codes_json""",
            (market, today_iso(), json.dumps(codes)),
        )
