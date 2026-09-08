"""Attribution challenges — the gate that catches an edge resting on one name."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.paper_trading.schedule import last_settled_session
from src.paper_trading.attribution import (
    settled_end, run_stability_challenge, BENCHMARK, ChallengeResult, judge, run_attribution,
)

UNI = [("AAPL", "us"), ("NVDA", "us"), ("MSFT", "us")]


def _cr(name, strat, bench, kind="leave_one_out"):
    return ChallengeResult(name, kind, strat, bench, survived=strat > bench)


# ── judge (pure) ─────────────────────────────────────────────────────────────
def test_no_edge_when_the_baseline_already_trails():
    verdict, weakest, summary = judge(_cr("全部", 0.4, 0.8, "baseline"), [])
    assert verdict == "no_edge"
    assert "未跑赢基准" in summary


def test_robust_only_when_every_challenge_survives():
    verdict, weakest, summary = judge(
        _cr("全部", 0.9, 0.8, "baseline"), [_cr("去掉 A", 0.7, 0.6), _cr("去掉 B", 0.75, 0.7)],
    )
    assert verdict == "robust" and weakest == ""
    # Surviving a few perturbations is weak evidence, and the wording must say so.
    assert "不等于优势已被证实" in summary


def test_one_failure_makes_it_fragile():
    verdict, weakest, _ = judge(
        _cr("全部", 0.95, 0.83, "baseline"),
        [_cr("去掉 AAPL", 0.7, 0.6), _cr("去掉 NVDA", 0.59, 0.62)],
    )
    assert verdict == "fragile"
    assert weakest == "去掉 NVDA"


def test_weakest_link_is_the_biggest_shortfall_not_the_first_failure():
    verdict, weakest, _ = judge(
        _cr("全部", 0.9, 0.8, "baseline"),
        [_cr("去掉 A", 0.79, 0.80), _cr("去掉 B", 0.22, 0.69)],
    )
    assert verdict == "fragile" and weakest == "去掉 B"


def test_no_runnable_challenges_is_not_treated_as_robust():
    verdict, _, summary = judge(_cr("全部", 0.9, 0.8, "baseline"), [])
    assert verdict == "fragile"
    assert "无法判断" in summary


# ── run_attribution (orchestration with an injected backtest) ────────────────
def _backtest_where(edge_needs: str | None, calmars: dict):
    """Fake runner: the strategy only beats the benchmark when ``edge_needs``
    is still in the universe."""
    def run(universe, start, end, strategy):
        codes = {c for c, _ in universe}
        if strategy == BENCHMARK:
            return {"calmar": calmars["bench"]}
        strong = edge_needs is None or edge_needs in codes
        return {"calmar": calmars["win"] if strong else calmars["lose"]}
    return run


def test_detects_an_edge_that_rests_on_a_single_name():
    report = run_attribution(
        UNI, "dual_momentum",
        _backtest_where("NVDA", {"bench": 0.83, "win": 0.95, "lose": 0.59}),
        start="2016-01-01", end="2026-01-01",
    )
    assert report.baseline.survived is True
    assert report.verdict == "fragile"
    assert report.weakest_link == "去掉 NVDA"


def test_reports_robust_when_no_single_name_carries_it():
    report = run_attribution(
        UNI, "s", _backtest_where(None, {"bench": 0.8, "win": 0.9, "lose": 0.0}),
        start="2016-01-01", end="2026-01-01",
    )
    assert report.verdict == "robust"
    assert all(c.survived for c in report.challenges)


def test_skips_challenges_entirely_when_the_baseline_loses():
    report = run_attribution(
        UNI, "s", _backtest_where(None, {"bench": 0.9, "win": 0.5, "lose": 0.5}),
        start="2016-01-01", end="2026-01-01",
    )
    assert report.verdict == "no_edge"
    assert report.challenges == []      # no point perturbing a losing strategy


def test_time_split_adds_two_challenges():
    report = run_attribution(
        UNI, "s", _backtest_where(None, {"bench": 0.8, "win": 0.9, "lose": 0.0}),
        start="2016-01-01", end="2026-01-01", split_date="2021-01-01",
    )
    kinds = [c.kind for c in report.challenges]
    assert kinds.count("time_split") == 2


def test_a_backtest_error_counts_as_a_failed_challenge_not_a_skip():
    def flaky(universe, start, end, strategy):
        if len(universe) < len(UNI):
            raise RuntimeError("data gap")
        return {"calmar": 0.9 if strategy != BENCHMARK else 0.8}

    report = run_attribution(UNI, "s", flaky, start="2016-01-01", end="2026-01-01")
    assert report.verdict == "fragile"
    assert all(not c.survived for c in report.challenges)
    assert "回测失败" in report.challenges[0].detail


def test_too_few_symbols_cannot_be_challenged():
    report = run_attribution(
        [("AAPL", "us")], "s", _backtest_where(None, {"bench": 0, "win": 1, "lose": 0}),
        start="2016-01-01", end="2026-01-01",
    )
    assert report.verdict == "no_edge"
    assert "不足 2 只" in report.summary


def test_report_serialises_with_margins():
    report = run_attribution(
        UNI, "s", _backtest_where("NVDA", {"bench": 0.83, "win": 0.95, "lose": 0.59}),
        start="2016-01-01", end="2026-01-01",
    )
    d = report.to_dict()
    assert d["verdict"] == "fragile" and d["total"] == len(d["challenges"])
    assert abs(d["baseline"]["margin"] - 0.12) < 1e-9


# --- settled-end gate -------------------------------------------------------
# Including today's still-moving bar made the same battery return different
# verdicts minutes apart, so the end date is trimmed to the last final session.

def _et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York"))


def test_last_settled_session_excludes_todays_unfinished_bar():
    # Tue 2026-09-08 11:00 ET — market open, today's bar is still moving.
    assert last_settled_session(_et(2026, 9, 8, 11)) == date(2026, 9, 7)


def test_last_settled_session_accepts_today_after_the_close():
    assert last_settled_session(_et(2026, 9, 8, 16, 30)) == date(2026, 9, 8)


def test_last_settled_session_skips_back_over_the_weekend():
    # Mon 09:00 ET: today is unfinished, and Sat/Sun have no bars -> Friday.
    assert last_settled_session(_et(2026, 9, 7, 9)) == date(2026, 9, 4)
    # Saturday, any hour, is also Friday.
    assert last_settled_session(_et(2026, 9, 5, 20)) == date(2026, 9, 4)


def test_settled_end_leaves_a_historical_end_date_alone():
    assert settled_end("2024-06-30", _et(2026, 9, 8, 11)) == "2024-06-30"


def test_run_attribution_trims_end_and_records_what_it_asked_for():
    seen: list[tuple[str, str]] = []

    def backtest(universe, start, end, strategy):
        seen.append((start, end))
        return {"calmar": 1.0 if strategy != BENCHMARK else 0.5}

    report = run_attribution(
        [("AAPL", "us"), ("MSFT", "us"), ("NVDA", "us")], "dual_momentum", backtest,
        start="2016-01-01", end="2026-09-08", now_et=_et(2026, 9, 8, 11),
    )

    assert report.end == "2026-09-07"
    assert report.requested_end == "2026-09-08"
    # No challenge may run against the unfinished bar.
    assert all(end == "2026-09-07" for _, end in seen)


def test_run_attribution_does_not_flag_a_trim_that_did_not_happen():
    report = run_attribution(
        [("AAPL", "us"), ("MSFT", "us")], "dual_momentum",
        lambda u, s, e, strat: {"calmar": 0.1},
        start="2016-01-01", end="2024-06-30", now_et=_et(2026, 9, 8, 11),
    )

    assert report.end == "2024-06-30"
    assert report.requested_end == ""


# --- stability challenge ----------------------------------------------------
# Motivated by a real miss: dual_momentum's Calmar moved across [0.760, 0.942]
# under 1e-7 price jitter while buy_and_hold stayed at 0.832 exactly. An edge
# thinner than that spread is a draw from a distribution, not a result.

def _seeded(strategy_values, bench_values):
    def fn(universe, start, end, strategy, seed):
        vals = strategy_values if strategy != BENCHMARK else bench_values
        return {"calmar": vals[seed % len(vals)]}
    return fn


def test_stability_fails_when_the_benchmark_falls_inside_the_strategys_swing():
    result = run_stability_challenge(
        UNI, "dual_momentum", _seeded([0.94, 0.76, 0.82], [0.832]),
        start="2016-01-01", end="2026-09-04", metric="calmar", seeds=3,
    )

    assert not result.survived
    # Scored at the worst draw, not the lucky one.
    assert result.strategy_metric == 0.76
    assert "0.760" in result.detail and "0.940" in result.detail


def test_stability_survives_only_when_every_draw_clears_the_benchmark():
    result = run_stability_challenge(
        UNI, "dual_momentum", _seeded([1.20, 1.18, 1.22], [0.832]),
        start="2016-01-01", end="2026-09-04", metric="calmar", seeds=3,
    )

    assert result.survived
    assert result.strategy_metric == 1.18


def test_stability_compares_against_the_benchmarks_own_best_draw():
    # A noisy benchmark must be given its best case, or the strategy gets
    # credit for the benchmark's bad luck.
    result = run_stability_challenge(
        UNI, "x", _seeded([1.0, 1.0], [0.5, 1.5]),
        start="2016-01-01", end="2026-09-04", metric="calmar", seeds=2,
    )

    assert not result.survived
    assert result.benchmark_metric == 1.5


def test_stability_challenge_counts_a_failed_run_as_failed():
    def boom(universe, start, end, strategy, seed):
        raise RuntimeError("no data")

    result = run_stability_challenge(
        UNI, "x", boom, start="2016-01-01", end="2026-09-04", metric="calmar", seeds=2,
    )

    assert not result.survived and "回测失败" in result.detail


def test_run_attribution_skips_stability_when_no_perturbed_runner_is_given():
    report = run_attribution(
        UNI, "dual_momentum", lambda u, s, e, strat: {"calmar": 1.0 if strat != BENCHMARK else 0.5},
        start="2016-01-01", end="2024-06-30",
    )

    assert not any(c.kind == "stability" for c in report.challenges)


def test_run_attribution_adds_the_stability_challenge_when_available():
    report = run_attribution(
        UNI, "dual_momentum", lambda u, s, e, strat: {"calmar": 1.0 if strat != BENCHMARK else 0.5},
        perturbed_backtest=_seeded([0.94, 0.76], [0.832]), stability_seeds=2,
        start="2016-01-01", end="2024-06-30",
    )

    stability = [c for c in report.challenges if c.kind == "stability"]
    assert len(stability) == 1 and not stability[0].survived
    # An unreproducible metric outranks a winning baseline: there is no edge to
    # call fragile, only a number that moves on its own.
    assert report.verdict == "no_edge"
    assert report.weakest_link == stability[0].name


def test_stability_runs_even_when_the_baseline_lost():
    # On a chaotic strategy the baseline verdict is itself one draw, so the
    # noise finding must still be reported rather than short-circuited away.
    report = run_attribution(
        UNI, "dual_momentum", lambda u, s, e, strat: {"calmar": 0.1 if strat != BENCHMARK else 0.9},
        perturbed_backtest=_seeded([0.94, 0.76], [0.832]), stability_seeds=2,
        start="2016-01-01", end="2024-06-30",
    )

    assert [c.kind for c in report.challenges] == ["stability"]
    assert report.verdict == "no_edge"
    assert "不是数据的稳定函数" in report.summary


def test_a_stable_winner_still_reads_as_robust():
    report = run_attribution(
        [("AAPL", "us"), ("MSFT", "us")], "x",
        lambda u, s, e, strat: {"calmar": 1.5 if strat != BENCHMARK else 0.5},
        perturbed_backtest=_seeded([1.48, 1.52], [0.83]), stability_seeds=2,
        start="2016-01-01", end="2024-06-30",
    )

    assert report.verdict == "robust"
