import sqlite3

from src.watchlist import WatchlistStore


def test_watchlist_changes_create_dated_membership_snapshots(tmp_path, monkeypatch):
    current = {"value": "2026-06-01"}
    monkeypatch.setattr("src.watchlist.today_iso", lambda: current["value"])
    store = WatchlistStore(tmp_path / "watchlist.db")

    store.set("hk", ["0700", "9988"])
    current["value"] = "2026-06-15"
    store.remove("hk", "9988")
    store.add("hk", "1810")

    assert store.get_as_of("hk", "2026-06-10") == ["0700", "9988"]
    assert store.get_as_of("hk", "2026-06-15") == ["0700", "1810"]


def test_existing_watchlist_is_saved_as_upgrade_baseline(tmp_path, monkeypatch):
    path = tmp_path / "watchlist.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE watchlist (market TEXT, code TEXT, sort_order INTEGER, PRIMARY KEY (market, code))")
        conn.execute("INSERT INTO watchlist VALUES ('us', 'NVDA', 0)")
    monkeypatch.setattr("src.watchlist.today_iso", lambda: "2026-06-30")

    store = WatchlistStore(path)

    assert store.get_as_of("us", "2026-06-30") == ["NVDA"]
