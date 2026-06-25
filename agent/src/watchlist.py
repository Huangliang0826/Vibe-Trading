"""SQLite-backed watchlist persistence."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.config.paths import get_runtime_root


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

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    market TEXT NOT NULL,
                    code TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (market, code)
                )
            """)

    def get(self, market: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT code FROM watchlist WHERE market = ? ORDER BY sort_order",
                (market,),
            ).fetchall()
        return [row["code"] for row in rows]

    def set(self, market: str, codes: list[str]) -> list[str]:
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist WHERE market = ?", (market,))
            for i, code in enumerate(codes):
                conn.execute(
                    "INSERT OR REPLACE INTO watchlist (market, code, sort_order) VALUES (?, ?, ?)",
                    (market, code.upper(), i),
                )
        return codes

    def add(self, market: str, code: str) -> list[str]:
        code = code.upper()
        with self._connect() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) as m FROM watchlist WHERE market = ?",
                (market,),
            ).fetchone()["m"]
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (market, code, sort_order) VALUES (?, ?, ?)",
                (market, code, max_order + 1),
            )
        return self.get(market)

    def remove(self, market: str, code: str) -> list[str]:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM watchlist WHERE market = ? AND code = ?",
                (market, code.upper()),
            )
        return self.get(market)
