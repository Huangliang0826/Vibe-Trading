from __future__ import annotations

from src.scanner.core import Candidate, ScanResult
from src.scanner import store as s


def _result() -> ScanResult:
    return ScanResult(
        universe="sp500", asof="2026-06-11", providers=["factor_rank"],
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
