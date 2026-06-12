from __future__ import annotations

import argparse
import json

from src.scanner import cli_handlers as h
from src.scanner.core import Candidate, ScanResult


def _make_args(**kw) -> argparse.Namespace:
    return argparse.Namespace(
        scan_cmd=kw.get("scan_cmd"),
        universe=kw.get("universe", "sp500"),
        asof=kw.get("asof", "2026-06-11"),
        top=kw.get("top", 20),
        json=kw.get("json", True),
        refresh_factors=kw.get("refresh_factors", False),
        verbose=False,
    )


def test_run_dispatch_invokes_core_and_saves(monkeypatch, tmp_path, capsys):
    result = ScanResult("sp500", "2026-06-11", ["factor_rank"],
                        [Candidate("AVGO", 92.4, "factor_rank", "top by f1", {})], [])
    monkeypatch.setattr(h, "_build_scan", lambda universe, asof, top: result)
    saved = {}
    monkeypatch.setattr(h, "save_scan", lambda r, **kw: saved.setdefault("r", r) or tmp_path)

    rc = h.dispatch(_make_args(scan_cmd="run"))
    assert rc == 0
    assert saved["r"].asof == "2026-06-11"
    out = json.loads(capsys.readouterr().out)
    assert out["candidates"][0]["symbol"] == "AVGO"


def test_show_dispatch_reads_latest(monkeypatch, capsys):
    result = ScanResult("sp500", "2026-06-11", ["factor_rank"],
                        [Candidate("CAT", 88.1, "factor_rank", "why", {})], [])
    monkeypatch.setattr(h, "load_latest", lambda **kw: result)
    rc = h.dispatch(_make_args(scan_cmd="show"))
    assert rc == 0
    assert "CAT" in capsys.readouterr().out


def test_show_dispatch_no_scans_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(h, "load_latest", lambda **kw: None)
    rc = h.dispatch(_make_args(scan_cmd="show"))
    assert rc == 1
