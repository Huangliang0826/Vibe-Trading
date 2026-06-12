from __future__ import annotations

import json

from src.scanner import manifest as m


def test_build_keeps_only_strict_passers_at_threshold(tmp_path):
    fake_strict = {
        "status": "ok",
        "alpha_t_threshold": 3.0,
        "rows": [
            {"id": "gtja_alpha_032", "zoo": "gtja191", "ir": 0.21,
             "alpha_t": 4.1, "category": "alive"},
            {"id": "a101_alpha_054", "zoo": "alpha101", "ir": 0.15,
             "alpha_t": 3.2, "category": "alive"},
            {"id": "noise_alpha_001", "zoo": "alpha101", "ir": 0.02,
             "alpha_t": 1.1, "category": "dead"},
        ],
    }

    def fake_runner(zoo, universe, period, **kwargs):
        assert universe == "sp500"
        assert kwargs.get("alpha_t_threshold") == 3.0
        return fake_strict

    out = tmp_path / "factor_whitelist.json"
    result = m.build_factor_manifest(
        zoos=["gtja191"], universe="sp500", period="2018-2025",
        out_path=out, runner=fake_runner,
    )

    assert {f["id"] for f in result["factors"]} == {"gtja_alpha_032", "a101_alpha_054"}
    assert result["threshold"] == 3.0
    saved = json.loads(out.read_text())
    assert saved == result
    weights = {f["id"]: f["ir"] for f in saved["factors"]}
    assert weights["gtja_alpha_032"] == 0.21


def test_load_missing_manifest_raises_actionable_error(tmp_path):
    try:
        m.load_factor_manifest(tmp_path / "nope.json")
    except FileNotFoundError as exc:
        assert "scan validate --refresh-factors" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")
