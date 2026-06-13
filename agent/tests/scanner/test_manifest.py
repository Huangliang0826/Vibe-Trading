from __future__ import annotations

import json

from src.scanner import manifest as m


def test_build_keeps_only_strict_passers_at_threshold(tmp_path):
    fake_strict = {
        "status": "ok",
        "alpha_t_threshold": 3.0,
        "rows": [
            {"id": "gtja_alpha_032", "ir": 0.21, "alpha_t_full": 4.1,
             "_category": "confirmed_alive"},
            {"id": "a101_alpha_054", "ir": 0.15, "alpha_t_full": 3.2,
             "_category": "confirmed_alive"},
            {"id": "noise_alpha_001", "ir": 0.02, "alpha_t_full": 1.1,
             "_category": "noise"},
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


def test_production_adapter_forwards_random_control_and_threshold(tmp_path, monkeypatch):
    # Pin the REAL adapter path (runner=None): it must pass random_control=True,
    # the oos_split, and a StrictThresholds carrying our alpha_t threshold.
    import src.factors.bench_runner_strict as strict

    captured = {}

    def spy_run_bench_strict(zoo, universe, period, **kwargs):
        captured["zoo"] = zoo
        captured["universe"] = universe
        captured.update(kwargs)
        return {"status": "ok", "rows": []}

    monkeypatch.setattr(strict, "run_bench_strict", spy_run_bench_strict)

    out = tmp_path / "wl.json"
    m.build_factor_manifest(
        zoos=["gtja191"], universe="sp500", period="2018-2025",
        out_path=out, threshold=3.0, oos_split="2023-01-01", runner=None,
    )

    assert captured["random_control"] is True
    assert captured["oos_split"] == "2023-01-01"
    # thresholds is a real StrictThresholds carrying our threshold
    assert captured["thresholds"].alpha_t_threshold == 3.0
