"""Tests for the daily scheduled scan + backfill."""
from __future__ import annotations

from src.scanner import schedule
from src.scanner.core import Candidate, ScanResult
from src.scanner.store import save_scan
from src.scanner.tracking import TrackingRecord, load_tracking, save_tracking


def _scan(asof: str, universe: str = "hstech") -> ScanResult:
    return ScanResult(
        universe, asof, ["factor_rank"],
        [Candidate("0700.HK", 90.0, "factor_rank", "top", {})], [],
    )


class TestBackfillUniverse:
    def test_creates_tracking_for_dates_without_records(self, tmp_path, monkeypatch):
        save_scan(_scan("2025-06-02"), root=tmp_path / "scans")
        seen = []
        monkeypatch.setattr(
            schedule, "backfill_returns",
            lambda asof, candidates, root, universe: seen.append(asof),
        )

        processed = schedule.backfill_universe(
            "hstech", scan_root=tmp_path / "scans", tracking_root=tmp_path / "tracking",
        )

        assert processed == ["2025-06-02"]
        assert seen == ["2025-06-02"]

    def test_skips_complete_records(self, tmp_path, monkeypatch):
        save_scan(_scan("2025-06-02"), root=tmp_path / "scans")
        save_tracking(
            [TrackingRecord("0700.HK", 90.0, "2025-06-02", entry_date="2025-06-03",
                            entry_price=100.0, fwd_1d=1.0, fwd_5d=2.0, fwd_20d=3.0)],
            "2025-06-02", root=tmp_path / "tracking", universe="hstech",
        )
        monkeypatch.setattr(
            schedule, "backfill_returns",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not backfill")),
        )

        processed = schedule.backfill_universe(
            "hstech", scan_root=tmp_path / "scans", tracking_root=tmp_path / "tracking",
        )

        assert processed == []

    def test_refreshes_overdue_records(self, tmp_path, monkeypatch):
        save_scan(_scan("2025-06-02"), root=tmp_path / "scans")
        # Old date, records still missing everything → overdue
        save_tracking(
            [TrackingRecord("0700.HK", 90.0, "2025-06-02")],
            "2025-06-02", root=tmp_path / "tracking", universe="hstech",
        )
        monkeypatch.setattr(schedule, "is_backfill_pending", lambda records, asof: True)
        seen = []
        monkeypatch.setattr(
            schedule, "backfill_returns",
            lambda asof, candidates, root, universe: seen.append((asof, universe)),
        )

        processed = schedule.backfill_universe(
            "hstech", scan_root=tmp_path / "scans", tracking_root=tmp_path / "tracking",
        )

        assert processed == ["2025-06-02"]
        assert seen == [("2025-06-02", "hstech")]


class TestRunDaily:
    def test_scans_then_backfills_and_isolates_failures(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            schedule, "scan_universe",
            lambda universe, top: calls.append(("scan", universe)) or "2025-06-02",
        )

        def fake_backfill(universe):
            calls.append(("backfill", universe))
            if universe == "sp500":
                raise RuntimeError("network down")
            return ["2025-06-02"]

        monkeypatch.setattr(schedule, "backfill_universe", fake_backfill)
        monkeypatch.setattr(schedule, "refresh_news", lambda: {"fetched": 2})

        results = schedule.run_daily(["hstech"], backfill_universes=["hstech", "sp500"])

        assert calls == [("scan", "hstech"), ("backfill", "hstech"), ("backfill", "sp500")]
        assert results[0] == {"universe": "hstech", "action": "scan", "asof": "2025-06-02"}
        assert results[1]["dates"] == ["2025-06-02"]
        assert results[2]["action"] == "backfill"
        assert "error" in results[2]
        assert results[-1] == {"action": "news", "fetched": 2}

    def test_weekend_skips_scan_but_still_backfills_and_news(self, monkeypatch):
        import datetime
        from types import SimpleNamespace

        class _Saturday(datetime.date):
            @classmethod
            def today(cls):
                return cls(2025, 6, 7)  # a Saturday

        monkeypatch.setattr(schedule, "dt", SimpleNamespace(date=_Saturday))
        monkeypatch.setattr(
            schedule, "scan_universe",
            lambda universe, top: (_ for _ in ()).throw(AssertionError("no scan on weekend")),
        )
        seen = []
        monkeypatch.setattr(
            schedule, "backfill_universe", lambda universe: seen.append(universe) or []
        )
        monkeypatch.setattr(schedule, "refresh_news", lambda: {"fetched": 5})

        results = schedule.run_daily(["hstech"], backfill_universes=["hstech"])

        # news still runs on weekends even though scans are skipped
        assert [r["action"] for r in results] == ["backfill", "news"]
        assert seen == ["hstech"]

    def test_scan_failure_does_not_block_backfill(self, monkeypatch):
        monkeypatch.setattr(
            schedule, "scan_universe",
            lambda universe, top: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr(schedule, "backfill_universe", lambda universe: [])
        monkeypatch.setattr(schedule, "refresh_news", lambda: {"fetched": 0})

        results = schedule.run_daily(["hstech"], backfill_universes=["hstech"])

        assert "error" in results[0]
        assert results[1] == {"universe": "hstech", "action": "backfill", "dates": []}

    def test_news_failure_is_isolated(self, monkeypatch):
        monkeypatch.setattr(schedule, "scan_universe", lambda universe, top: "2025-06-02")
        monkeypatch.setattr(schedule, "backfill_universe", lambda universe: [])
        monkeypatch.setattr(
            schedule, "refresh_news",
            lambda: (_ for _ in ()).throw(RuntimeError("feeds down")),
        )

        results = schedule.run_daily(["hstech"], backfill_universes=["hstech"])

        news = results[-1]
        assert news["action"] == "news"
        assert "error" in news
