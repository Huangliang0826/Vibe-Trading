from __future__ import annotations

import json

from src.scanner.core import Candidate, ScanResult
from src.scanner import store as s


def _result(universe: str = "sp500", asof: str = "2026-06-11") -> ScanResult:
    return ScanResult(
        universe=universe, asof=asof, providers=["factor_rank"],
        candidates=[Candidate("AVGO", 92.4, "factor_rank", "top by f1", {"f1": 34.1})],
        warnings=[],
    )


def test_save_then_load_latest_roundtrips(tmp_path):
    path = s.save_scan(_result(), root=tmp_path)
    assert path.is_file()
    loaded = s.load_scan(path)
    assert loaded.to_dict() == _result().to_dict()


def test_load_latest_returns_most_recent_asof(tmp_path):
    older = ScanResult("sp500", "2026-06-10", ["factor_rank"], [], [])
    s.save_scan(older, root=tmp_path)
    s.save_scan(_result(), root=tmp_path)
    latest = s.load_latest(root=tmp_path)
    assert latest is not None and latest.asof == "2026-06-11"


def test_load_latest_none_when_empty(tmp_path):
    assert s.load_latest(root=tmp_path) is None


def test_same_date_scans_are_isolated_by_universe(tmp_path):
    for universe in ("sp500", "csi300", "hstech"):
        s.save_scan(_result(universe=universe), root=tmp_path)

    assert s.list_scan_dates("sp500", root=tmp_path) == ["2026-06-11"]
    assert s.load_by_date("2026-06-11", "csi300", root=tmp_path).universe == "csi300"
    assert s.load_latest("hstech", root=tmp_path).universe == "hstech"


def test_legacy_scan_path_is_filtered_by_universe(tmp_path):
    legacy = tmp_path / "2026-06-11"
    legacy.mkdir()
    path = legacy / "run.json"
    path.write_text(json.dumps(_result("sp500").to_dict()), encoding="utf-8")

    assert s.list_scan_dates("sp500", root=tmp_path) == ["2026-06-11"]
    assert s.load_latest("sp500", root=tmp_path).universe == "sp500"
    assert s.list_scan_dates("hstech", root=tmp_path) == []
    assert s.load_by_date("2026-06-11", "hstech", root=tmp_path) is None
