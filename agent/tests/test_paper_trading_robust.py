from __future__ import annotations

import pandas as pd
import pytest

from src.paper_trading.robust import _build_windows, _common_data_span, _history_start_date
from src.paper_trading.models import RobustOptimizeCreate


def _frame(start: str, end: str) -> pd.DataFrame:
    index = pd.bdate_range(start, end)
    return pd.DataFrame({"close": range(1, len(index) + 1)}, index=index)


def test_history_start_date_caps_fetch_at_twenty_years() -> None:
    assert _history_start_date("2026-07-02") == "2006-07-02"


def test_robust_request_does_not_require_a_start_date() -> None:
    request = RobustOptimizeCreate.model_validate({
        "holdings": [{"symbol": "NVDA", "market": "us", "allocation_pct": 100}],
        "strategies": [{"name": "buy_and_hold", "params": {}}],
        "end_date": "2026-07-02",
    })

    assert request.start_date is None
    assert request.step_years == 1


def test_three_year_windows_roll_forward_every_year_without_dropping_early_periods() -> None:
    windows = _build_windows(
        pd.Timestamp("2006-07-02"), pd.Timestamp("2026-07-02"),
        window_years=3, step_years=1,
    )
    labels = [window["label"] for window in windows]

    assert labels[:3] == ["2006–2009", "2007–2010", "2008–2011"]
    assert "2012–2015" in labels
    assert "2013–2016" in labels
    assert labels[-1] == "全历史"
    assert len(labels) == 19


def test_common_data_span_uses_latest_listing_and_earliest_last_date() -> None:
    data = {
        "OLD": _frame("2006-07-03", "2026-07-02"),
        "NEW": _frame("2021-03-15", "2026-07-01"),
    }

    start, end, limiting = _common_data_span(data, ["OLD", "NEW"])

    assert start == pd.Timestamp("2021-03-15")
    assert end == pd.Timestamp("2026-07-01")
    assert limiting == ["NEW"]


def test_common_data_span_rejects_missing_portfolio_symbols() -> None:
    with pytest.raises(ValueError, match="MISSING"):
        _common_data_span({"OLD": _frame("2020-01-01", "2026-01-01")}, ["OLD", "MISSING"])


# ── Baseline comparison & top-k ensemble ────────────────────────────────────

from src.paper_trading.robust import (  # noqa: E402
    _build_ensemble,
    _mean_excess_vs_cells,
    _windows_beating,
)


def _ok(score: float, total_return: float, max_loss: float = 0.0) -> dict:
    return {"score": score, "total_return": total_return, "max_loss": max_loss, "status": "ok"}


def test_mean_excess_vs_cells_pairs_only_windows_where_both_succeeded() -> None:
    row = [_ok(1.0, 0.30), {"status": "failed"}, _ok(1.0, 0.10)]
    bh = [_ok(0.5, 0.20), _ok(0.5, 0.99), _ok(0.5, 0.20)]

    # (0.30-0.20 + 0.10-0.20) / 2 — the failed middle window is excluded.
    assert _mean_excess_vs_cells(row, bh) == pytest.approx(0.0)


def test_mean_excess_vs_cells_returns_none_without_paired_windows() -> None:
    assert _mean_excess_vs_cells([{"status": "failed"}], [_ok(0.5, 0.2)]) is None


def test_windows_beating_counts_score_wins_over_buy_and_hold() -> None:
    row = [_ok(1.0, 0.3), _ok(0.4, 0.1), {"status": "failed"}]
    bh = [_ok(0.5, 0.2), _ok(0.5, 0.2), _ok(0.5, 0.2)]

    assert _windows_beating(row, bh) == {"beating": 1, "total": 2}


def _linear_curve(start: str, periods: int, initial: float, final: float) -> pd.Series:
    index = pd.bdate_range(start, periods=periods)
    values = [initial + (final - initial) * i / (periods - 1) for i in range(periods)]
    return pd.Series(values, index=index, dtype=float)


def test_build_ensemble_blends_topk_curves_with_equal_capital() -> None:
    windows = [{"label": "w0"}]
    cash = 100_000.0
    strategies = [
        {"name": "a", "ok_count": 1, "mean_score": 0.5},
        {"name": "b", "ok_count": 1, "mean_score": 0.4},
        {"name": "c", "ok_count": 1, "mean_score": 0.3},
    ]
    cells = {n: [_ok(0.5, 0.2)] for n in ("a", "b", "c")}
    curves = {
        ("a", 0): _linear_curve("2024-01-01", 300, cash, cash * 1.30),
        ("b", 0): _linear_curve("2024-01-01", 300, cash, cash * 1.10),
        ("c", 0): _linear_curve("2024-01-01", 300, cash, cash * 0.90),
    }

    ensemble = _build_ensemble(strategies, cells, curves, windows, cash, None)

    assert ensemble is not None
    assert ensemble["members"] == ["a", "b", "c"]
    assert ensemble["ok_count"] == 1
    # Equal-capital blend of +30% / +10% / −10% = +10%.
    assert ensemble["cells"][0]["total_return"] == pytest.approx(0.10, abs=1e-6)
    assert ensemble["mean_excess_vs_hold"] is None


def test_build_ensemble_marks_window_failed_when_any_member_curve_missing() -> None:
    windows = [{"label": "w0"}, {"label": "w1"}]
    cash = 100_000.0
    strategies = [
        {"name": "a", "ok_count": 2, "mean_score": 0.5},
        {"name": "b", "ok_count": 1, "mean_score": 0.4},
    ]
    cells = {"a": [_ok(0.5, 0.2)] * 2, "b": [_ok(0.5, 0.2), {"status": "failed"}]}
    curves = {
        ("a", 0): _linear_curve("2024-01-01", 300, cash, cash * 1.2),
        ("b", 0): _linear_curve("2024-01-01", 300, cash, cash * 1.2),
        ("a", 1): _linear_curve("2025-01-01", 300, cash, cash * 1.2),
        # ("b", 1) missing — that window failed for b.
    }

    ensemble = _build_ensemble(strategies, cells, curves, windows, cash, None)

    assert ensemble is not None
    assert ensemble["cells"][0]["status"] == "ok"
    assert ensemble["cells"][1]["status"] == "failed"
    assert ensemble["ok_count"] == 1


def test_build_ensemble_requires_at_least_two_members() -> None:
    strategies = [{"name": "a", "ok_count": 1, "mean_score": 0.5}]
    assert _build_ensemble(strategies, {}, {}, [{"label": "w0"}], 1.0, None) is None


# ── ±25% parameter sensitivity ───────────────────────────────────────────────

from src.paper_trading.robust import (  # noqa: E402
    _PERTURB_SPECS,
    _param_sensitivity,
    _perturbed_value,
)


def test_perturbed_value_scales_ints_with_rounding_and_floor() -> None:
    assert _perturbed_value(200, 0.75) == 150
    assert _perturbed_value(200, 1.25) == 250
    assert _perturbed_value(5, 0.75) == 4      # round(3.75) = 4
    assert _perturbed_value(1, 0.75) == 1      # floor at 1
    assert _perturbed_value(0.4, 0.75) == pytest.approx(0.3)
    assert _perturbed_value(0.4, 1.25) == pytest.approx(0.5)


def test_perturb_specs_only_name_registered_strategies() -> None:
    from src.paper_trading.hstech_best import STRATEGY_NAMES

    unknown = set(_PERTURB_SPECS) - set(STRATEGY_NAMES)
    assert not unknown, f"specs reference unregistered strategies: {unknown}"


def _windows_one() -> list[dict]:
    return [{"label": "w0", "start": pd.Timestamp("2024-01-01"), "end": pd.Timestamp("2025-01-01")}]


def test_param_sensitivity_no_params_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    strategies = [{"name": "buy_and_hold", "mean_score": 0.5}]
    out = _param_sensitivity(strategies, [{"name": "buy_and_hold", "params": {}}],
                             [], {}, _windows_one(), 1.0, None)

    assert out[0]["verdict"] == "no_params"
    assert out[0]["variants"] == []


def test_param_sensitivity_robust_and_sensitive_vs_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.paper_trading.robust as robust_mod

    # Fake evaluator: ma200_timing variants stay strong; trailing_stop variants collapse.
    def fake_eval(holdings, sliced, name, params, cash):
        idx = pd.bdate_range("2024-01-01", periods=50)
        final = 1.3 if name == "ma200_timing" else 0.8
        curve = pd.Series([cash * (1 + (final - 1) * i / 49) for i in range(50)], index=idx)
        return curve, []

    monkeypatch.setattr(robust_mod, "evaluate_strategy", fake_eval)

    bh_cells = [{"score": 0.0, "total_return": 0.0, "max_loss": 0.0, "status": "ok"}]
    strategies = [
        {"name": "ma200_timing", "mean_score": 0.35},
        {"name": "trailing_stop", "mean_score": 0.30},
    ]
    specs = [{"name": "ma200_timing", "params": {}}, {"name": "trailing_stop", "params": {}}]
    data_map = {"X": _frame("2024-01-02", "2024-12-31")}

    out = _param_sensitivity(strategies, specs, [], data_map, _windows_one(), 100_000.0, bh_cells)

    by_name = {r["name"]: r for r in out}
    # +30% variants beat the 0.0 baseline score → robust.
    assert by_name["ma200_timing"]["verdict"] == "robust"
    assert len(by_name["ma200_timing"]["variants"]) == 2  # one param × two factors
    # −20% variants score below baseline → sensitive.
    assert by_name["trailing_stop"]["verdict"] == "sensitive"
    assert len(by_name["trailing_stop"]["variants"]) == 4  # two params × two factors


def test_param_sensitivity_all_variants_failing_is_sensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.paper_trading.robust as robust_mod

    def broken_eval(*args, **kwargs):
        raise ValueError("no fit")

    monkeypatch.setattr(robust_mod, "evaluate_strategy", broken_eval)

    strategies = [{"name": "grid", "mean_score": 0.2}]
    out = _param_sensitivity(strategies, [{"name": "grid", "params": {"grid_count": 5}}],
                             [], {"X": _frame("2024-01-02", "2024-12-31")}, _windows_one(), 1.0,
                             [{"score": 0.0, "status": "ok"}])

    assert out[0]["verdict"] == "sensitive"
    assert out[0]["worst_score"] is None
