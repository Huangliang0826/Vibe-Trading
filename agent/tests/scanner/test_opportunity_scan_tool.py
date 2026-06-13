from __future__ import annotations

import json

from src.scanner.core import Candidate, ScanResult
import src.tools.opportunity_scan_tool as t


def test_tool_returns_latest_scan_json(monkeypatch):
    result = ScanResult("sp500", "2026-06-11", ["factor_rank"],
                        [Candidate("AVGO", 92.4, "factor_rank", "top by f1", {})], [])
    monkeypatch.setattr(t, "load_latest", lambda **kw: result)

    tool = t.OpportunityScanTool()
    out = json.loads(tool.execute())
    assert out["status"] == "ok"
    assert out["scan"]["candidates"][0]["symbol"] == "AVGO"


def test_tool_errors_cleanly_when_no_scan(monkeypatch):
    monkeypatch.setattr(t, "load_latest", lambda **kw: None)
    tool = t.OpportunityScanTool()
    out = json.loads(tool.execute())
    assert out["status"] == "error"
    assert "no scan" in out["error"].lower()
