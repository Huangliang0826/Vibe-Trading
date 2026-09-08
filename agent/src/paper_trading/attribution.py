"""Attribution challenges — does a strategy's edge survive perturbation?

A backtest that beats its benchmark proves very little on its own. The edge may
rest entirely on one lucky name, or on one favourable stretch of history. This
module re-runs the same strategy under deliberate perturbations and reports
which challenges the edge actually survives.

It exists because of a concrete miss: cross-sectional dual momentum beat
equal-weight buy-and-hold on a 10-name US universe (Calmar 0.95 vs 0.83), but
removing NVDA flipped it to a loss — the "edge" was one position. Overfitting
does not only happen in parameters; it happens in universe selection and in the
window you happen to test.

The battery also asks whether the metric is a *stable* function of the data at
all. Some strategies are chaotic: cross-sectional dual momentum holding a single
name flips that month's winner when two trailing returns are nearly tied, so
float-rounding noise of 1e-7 moved its Calmar across [0.760, 0.942] while
buy-and-hold stayed at 0.832 to the digit. A measured "edge" narrower than that
spread is a draw from a distribution, not a finding.

Backtests here always stop at the last *settled* session. Including today's
still-moving bar makes the whole battery irreproducible: on this very universe
the same run gave Calmar 0.94 and 0.90 on two consecutive fetches minutes apart,
which is larger than the edge being measured.

The verdict is deliberately conservative: an edge that fails ANY challenge is
reported as fragile, never as established. Same stance as the edge scorecard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Sequence

from src.paper_trading.schedule import et_now, last_settled_session

#: A backtest runner: (universe, start, end, strategy) -> metrics dict.
#: Must return at least {"total_return", "calmar"}; injected so the pure
#: judging logic stays testable without running real backtests.
BacktestFn = Callable[[Sequence[tuple[str, str]], str, str, str], dict]

#: Same call plus a seed, where the seed applies a tiny relative jitter to the
#: input prices. Optional; without it the stability challenge cannot run.
PerturbedBacktestFn = Callable[[Sequence[tuple[str, str]], str, str, str, int], dict]

BENCHMARK = "buy_and_hold"

#: Jitter seeds for the stability challenge. Eight is enough to expose a
#: strategy whose metric swings by more than its entire edge; more is cheap
#: but each seed is a full backtest.
STABILITY_SEEDS = 8


@dataclass(frozen=True)
class ChallengeResult:
    name: str            # human-readable, e.g. "去掉 NVDA"
    kind: str            # baseline | leave_one_out | time_split
    strategy_metric: Optional[float]
    benchmark_metric: Optional[float]
    survived: bool
    detail: str = ""

    @property
    def margin(self) -> Optional[float]:
        if self.strategy_metric is None or self.benchmark_metric is None:
            return None
        return self.strategy_metric - self.benchmark_metric

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind,
            "strategy_metric": self.strategy_metric,
            "benchmark_metric": self.benchmark_metric,
            "margin": self.margin,
            "survived": self.survived, "detail": self.detail,
        }


@dataclass
class AttributionReport:
    strategy: str
    metric: str
    universe: list[str]
    start: str = ""
    end: str = ""              # the settled end actually tested
    requested_end: str = ""    # what the caller asked for, if it was trimmed
    baseline: Optional[ChallengeResult] = None
    challenges: list[ChallengeResult] = field(default_factory=list)
    verdict: str = "no_edge"       # no_edge | fragile | robust
    weakest_link: str = ""
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy, "metric": self.metric, "universe": self.universe,
            "start": self.start, "end": self.end, "requested_end": self.requested_end,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "challenges": [c.to_dict() for c in self.challenges],
            "survived": sum(1 for c in self.challenges if c.survived),
            "total": len(self.challenges),
            "verdict": self.verdict, "weakest_link": self.weakest_link,
            "summary": self.summary,
        }


def judge(baseline: Optional[ChallengeResult], challenges: Sequence[ChallengeResult]) -> tuple[str, str, str]:
    """Return (verdict, weakest_link, summary) — pure, no I/O.

    * ``no_edge``  — the strategy does not beat the benchmark to begin with, or
      its metric is not reproducible enough for "beat" to mean anything.
    * ``fragile``  — it wins at baseline but at least one challenge breaks it.
    * ``robust``   — it wins at baseline and survives every challenge.

    "Robust" here means "not obviously fragile", not "proven". Surviving a
    handful of perturbations on one universe is weak evidence.
    """
    unstable = next((c for c in challenges if c.kind == "stability" and not c.survived), None)
    if unstable is not None:
        return (
            "no_edge", unstable.name,
            "策略指标不是数据的稳定函数——极小的价格扰动就能让它跨过基准线。"
            f"{unstable.detail}单次回测的胜负只是一次抽样,不构成优势。",
        )
    if baseline is None or not baseline.survived:
        return ("no_edge", "", "策略未跑赢基准,归因检验无从谈起。")
    if not challenges:
        return ("fragile", "", "没有可执行的挑战项(标的或区间不足),无法判断稳健性。")

    failed = [c for c in challenges if not c.survived]
    if not failed:
        return (
            "robust", "",
            f"通过全部 {len(challenges)} 项挑战。注意:这只说明它没有明显脆弱点,"
            "不等于优势已被证实——单一标的池上的少量扰动是弱证据。",
        )

    # The worst failure is the one where the strategy trails the benchmark most.
    def gap(c: ChallengeResult) -> float:
        return c.margin if c.margin is not None else 0.0

    worst = min(failed, key=gap)
    return (
        "fragile", worst.name,
        f"{len(failed)}/{len(challenges)} 项挑战失败,最脆弱的是「{worst.name}」——"
        "基准优势主要来自这里,不能视为可复用的策略优势。",
    )


def settled_end(requested_end: str, now_et: Optional[datetime] = None) -> str:
    """Trim ``requested_end`` back to the last session with final bars."""
    limit = last_settled_session(now_et or et_now()).isoformat()
    return min(requested_end, limit)


def run_stability_challenge(
    universe: Sequence[tuple[str, str]],
    strategy: str,
    perturbed_backtest: PerturbedBacktestFn,
    *,
    start: str,
    end: str,
    metric: str,
    seeds: int = STABILITY_SEEDS,
) -> ChallengeResult:
    """Re-run under tiny price jitter; the edge must survive its own noise floor.

    Scored at the worst case deliberately: the strategy is credited with its
    *lowest* metric across seeds and the benchmark with its *highest*, so an
    edge only survives if it holds on every draw.
    """
    name = f"数据微扰({seeds} 次)"
    try:
        strat_runs = [_metric_of(perturbed_backtest(universe, start, end, strategy, i), metric)
                      for i in range(seeds)]
        bench_runs = [_metric_of(perturbed_backtest(universe, start, end, BENCHMARK, i), metric)
                      for i in range(seeds)]
    except Exception as exc:  # noqa: BLE001 - a failed run is a failed challenge
        return ChallengeResult(name, "stability", None, None, False, f"回测失败:{exc}")

    if any(v is None for v in strat_runs + bench_runs) or not strat_runs:
        return ChallengeResult(name, "stability", None, None, False, "指标缺失,无法比较")

    worst, best = min(strat_runs), max(strat_runs)
    spread = best - worst
    bench_worst_case = max(bench_runs)
    return ChallengeResult(
        name, "stability", worst, bench_worst_case, worst > bench_worst_case,
        f"策略波动区间 [{worst:.3f}, {best:.3f}],跨度 {spread:.3f};"
        f"基准跨度 {max(bench_runs) - min(bench_runs):.3f}。",
    )


def _metric_of(result: Optional[dict], metric: str) -> Optional[float]:
    if not isinstance(result, dict):
        return None
    value = result.get(metric)
    return float(value) if isinstance(value, (int, float)) else None


def run_attribution(
    universe: Sequence[tuple[str, str]],
    strategy: str,
    backtest: BacktestFn,
    *,
    start: str,
    end: str,
    metric: str = "calmar",
    split_date: Optional[str] = None,
    max_leave_one_out: int = 12,
    perturbed_backtest: Optional[PerturbedBacktestFn] = None,
    stability_seeds: int = STABILITY_SEEDS,
    now_et: Optional[datetime] = None,
) -> AttributionReport:
    """Run the challenge battery and judge the result.

    Challenges:
      * leave-one-out over every symbol (capped) — catches an edge that rests
        on a single name, the failure mode that motivated this module;
      * a time split — catches an edge confined to one stretch of history;
      * price jitter (only when ``perturbed_backtest`` is supplied) — catches an
        edge narrower than the strategy's own numerical noise floor.

    A challenge that errors is recorded as failed rather than skipped: an
    unverifiable claim is not a surviving one.

    ``end`` is trimmed to the last settled session so repeated runs agree.
    """
    requested_end = end
    end = settled_end(end, now_et)
    report = AttributionReport(strategy=strategy, metric=metric,
                               universe=[code for code, _ in universe],
                               start=start, end=end,
                               requested_end=requested_end if requested_end != end else "")

    def compare(uni: Sequence[tuple[str, str]], s: str, e: str, name: str, kind: str) -> ChallengeResult:
        try:
            strat = _metric_of(backtest(uni, s, e, strategy), metric)
            bench = _metric_of(backtest(uni, s, e, BENCHMARK), metric)
        except Exception as exc:  # noqa: BLE001 - a failed run is a failed challenge
            return ChallengeResult(name, kind, None, None, False, f"回测失败:{exc}")
        if strat is None or bench is None:
            return ChallengeResult(name, kind, strat, bench, False, "指标缺失,无法比较")
        return ChallengeResult(name, kind, strat, bench, strat > bench)

    if len(universe) < 2:
        report.verdict, report.weakest_link, report.summary = judge(None, [])
        report.summary = "标的不足 2 只,无法做归因检验。"
        return report

    report.baseline = compare(universe, start, end, "全部标的(基准对照)", "baseline")

    challenges: list[ChallengeResult] = []
    # Stability runs even when the baseline lost: on a chaotic strategy the
    # baseline verdict is itself a coin flip, and saying so is the useful answer.
    if perturbed_backtest is not None:
        challenges.append(run_stability_challenge(
            universe, strategy, perturbed_backtest,
            start=start, end=end, metric=metric, seeds=stability_seeds,
        ))
    if report.baseline.survived:
        for code, market in list(universe)[:max_leave_one_out]:
            reduced = [x for x in universe if x[0] != code]
            if len(reduced) < 2:
                continue
            challenges.append(compare(reduced, start, end, f"去掉 {code}", "leave_one_out"))
        if split_date:
            challenges.append(compare(universe, start, split_date, f"{start[:4]}–{split_date[:4]}", "time_split"))
            challenges.append(compare(universe, split_date, end, f"{split_date[:4]}–{end[:4]}", "time_split"))

    report.challenges = challenges
    report.verdict, report.weakest_link, report.summary = judge(report.baseline, challenges)
    return report
