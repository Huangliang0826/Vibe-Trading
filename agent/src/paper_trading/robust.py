"""Multi-period (robust) strategy optimisation for paper trading.

Instead of crowning the single-window winner (which overfits to one regime),
this evaluates every strategy across several fixed-length rolling windows plus
the full history, ranks the strategies *within each window* by the balance
score (total_return − 2×|max_loss|), and picks the strategy with the best
**average rank**. Consistency (worst rank, rank spread) is surfaced alongside
so the user can see robustness, not just a single champion.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.metrics import calc_metrics
from src.paper_trading.executor import evaluate_strategy
from src.paper_trading.models import PaperHolding
from src.paper_trading.strategies import _to_code

logger = logging.getLogger(__name__)

MAX_LOSS_PENALTY = 2.0  # mirrors the frontend balanceScore weight
_MAX_WINDOWS = 20        # full 20-year span: up to 18 three-year windows + full history
_MAX_HISTORY_YEARS = 20
_BASELINE_STRATEGY = "buy_and_hold"  # honest yardstick every strategy must beat
_ENSEMBLE_SIZE = 3       # top-k blend to dampen single-winner selection luck
_PERTURB_FACTORS = (0.75, 1.25)  # ±25% wiggle on each key parameter

# Key numeric parameter(s) per strategy for the ±25% sensitivity check, as
# (param, default) pairs mirroring the generators' internal defaults. A winner
# whose edge evaporates under this wiggle likely won on parameter luck, not on
# a real effect. Strategies absent here (or with an empty list) are cadence- or
# identity-parameterised only and are reported as having no key parameters.
_PERTURB_SPECS: Dict[str, List[tuple]] = {
    # NOTE: dca/smart_dca/value_averaging run through the executor simulators,
    # whose only knobs are cadence (frequency) — no numeric params to perturb.
    "grid": [("grid_count", 5)],
    "momentum_breakout": [("lookback", 20), ("stop_loss", 0.08)],
    "moving_average_cross": [("short_window", 20), ("long_window", 60)],
    "ma200_timing": [("window", 200)],
    "rsi_reversion": [("window", 14), ("buy_below", 35.0)],
    "volatility_target": [("target_vol", 0.18)],
    "drawdown_rebalance": [("first_level", 0.05), ("third_level", 0.15)],
    "trend_volatility_filter": [("ma_window", 120), ("target_vol", 0.18)],
    "donchian_breakout": [("entry_window", 55), ("exit_window", 20)],
    "bollinger_reversion": [("window", 20), ("band_width", 2.0)],
    "trailing_stop": [("trailing_stop", 0.12), ("ma_window", 60)],
    "atr_trend_stop": [("atr_multiple", 3.0), ("ma_window", 80)],
    "mean_reversion_scaleout": [("window", 20), ("stop_loss", 0.12)],
    "enhanced_dca_trend": [("ma_window", 120)],
    "breakout_pullback": [("breakout_window", 50), ("pullback_pct", 0.05)],
    "quality_momentum": [("lookback", 120)],
    "low_volatility_rotation": [("trend_window", 120)],
    "volatility_squeeze_breakout": [("width_quantile", 0.25), ("stop_loss", 0.10)],
    "risk_parity": [("window", 60)],
    "price_volume_efficiency": [("lookback", 60)],
    "macd_divergence": [("fast", 12), ("slow", 26)],
    "dual_momentum": [("lookback", 120)],
    "accelerated_dca_entry": [("accelerate_drawdown", 0.1), ("all_in_drawdown", 0.2)],
    "deep_drawdown_recovery": [("drawdown_threshold", 0.4), ("take_profit_pct", 0.4)],
}


def _balance_score(metrics: Dict[str, Any]) -> float:
    ret = float(metrics.get("total_return", 0.0) or 0.0)
    loss = abs(float(metrics.get("max_loss", 0.0) or 0.0))
    return ret - MAX_LOSS_PENALTY * loss


def _history_start_date(end_date: str, max_years: int = _MAX_HISTORY_YEARS) -> str:
    end = pd.Timestamp(end_date)
    return (end - pd.DateOffset(years=max_years)).strftime("%Y-%m-%d")


def _common_data_span(
    data_map: Dict[str, pd.DataFrame],
    required_codes: List[str],
) -> tuple[pd.Timestamp, pd.Timestamp, List[str]]:
    missing = [code for code in required_codes if code not in data_map or len(data_map[code]) < 2]
    if missing:
        raise ValueError(f"No price data for: {', '.join(missing)}")

    starts = {
        code: pd.Timestamp(pd.to_datetime(data_map[code].index).min()).tz_localize(None)
        for code in required_codes
    }
    ends = {
        code: pd.Timestamp(pd.to_datetime(data_map[code].index).max()).tz_localize(None)
        for code in required_codes
    }
    span_start = max(starts.values())
    span_end = min(ends.values())
    if span_start >= span_end:
        raise ValueError("Portfolio holdings have no overlapping price history")
    limiting = sorted(code for code, start in starts.items() if start == span_start)
    return span_start, span_end, limiting


def _build_windows(
    span_start: pd.Timestamp,
    span_end: pd.Timestamp,
    window_years: int,
    step_years: int,
) -> List[Dict[str, Any]]:
    """Rolling ``window_years`` windows stepped by ``step_years`` + full span.

    Falls back to a single full-span window when the data is shorter than one
    window length.
    """
    win = pd.DateOffset(years=window_years)
    step = pd.DateOffset(years=max(step_years, 1))
    total_days = (span_end - span_start).days

    windows: List[tuple] = []
    if total_days < window_years * 365 - 30:
        windows.append((span_start, span_end))
    else:
        w_start = span_start
        while w_start + win <= span_end + pd.Timedelta(days=2):
            windows.append((w_start, w_start + win))
            w_start = w_start + step
        # Always anchor a final window to the most recent data.
        last_start = span_end - win
        if not windows or (last_start - windows[-1][0]).days > 60:
            windows.append((last_start, span_end))
        # Full-history window as an extra robustness check.
        windows.append((span_start, span_end))

    # Dedup by year-range (keep the latest-ending variant so the recent tail
    # stays covered), preserving chronological order.
    by_key: Dict[tuple, tuple] = {}
    for s, e in windows:
        key = (s.year, e.year)
        if key not in by_key or e > by_key[key][1]:
            by_key[key] = (s, e)
    rolling, full = [], []
    for s, e in sorted(by_key.values(), key=lambda se: se[0]):
        is_full = s <= span_start + pd.Timedelta(days=5) and e >= span_end - pd.Timedelta(days=5)
        entry = {
            "start": s, "end": e,
            "label": "全历史" if is_full else f"{s.year}–{e.year}",
            "is_full": bool(is_full),
        }
        (full if is_full else rolling).append(entry)
    out = rolling + full  # rolling windows chronological, full-history last
    # Keep the most recent rolling windows + the full one if over the cap.
    if len(out) > _MAX_WINDOWS:
        full = [w for w in out if w["is_full"]]
        rolling = [w for w in out if not w["is_full"]]
        out = rolling[-(_MAX_WINDOWS - len(full)):] + full
    return out


def _mean_excess_vs_cells(
    row: List[Optional[Dict[str, Any]]],
    bh_row: List[Optional[Dict[str, Any]]],
) -> Optional[float]:
    """Mean per-window return difference vs buy & hold (paired windows only)."""
    diffs = [
        c["total_return"] - b["total_return"]
        for c, b in zip(row, bh_row)
        if c and b and c.get("status") == "ok" and b.get("status") == "ok"
    ]
    return round(float(np.mean(diffs)), 6) if diffs else None


def _windows_beating(
    row: List[Optional[Dict[str, Any]]],
    bh_row: List[Optional[Dict[str, Any]]],
) -> Optional[Dict[str, int]]:
    """Count windows where the strategy's balance score beats buy & hold's."""
    paired = [
        (c, b)
        for c, b in zip(row, bh_row)
        if c and b and c.get("status") == "ok" and b.get("status") == "ok"
    ]
    if not paired:
        return None
    beating = sum(1 for c, b in paired if c["score"] > b["score"])
    return {"beating": beating, "total": len(paired)}


def _perturbed_value(base: Any, factor: float) -> Any:
    """Scale a numeric param by ``factor``; ints round and stay ≥ 1."""
    if isinstance(base, int) and not isinstance(base, bool):
        return max(int(round(base * factor)), 1)
    return round(float(base) * factor, 6)


def _evaluate_over_windows(
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    name: str,
    params: Dict[str, Any],
    windows: List[Dict[str, Any]],
    initial_cash: float,
) -> List[Optional[Dict[str, Any]]]:
    """Slim window sweep for sensitivity variants (metrics only, no curves)."""
    out: List[Optional[Dict[str, Any]]] = []
    for w in windows:
        sliced = {c: df.loc[w["start"]:w["end"]] for c, df in data_map.items()}
        sliced = {c: df for c, df in sliced.items() if df is not None and len(df) >= 2}
        try:
            if not sliced:
                raise ValueError("No data in window")
            equity_series, trades = evaluate_strategy(
                holdings, sliced, name, params, initial_cash,
            )
            if equity_series is None or len(equity_series) < 2:
                raise ValueError("Empty equity curve")
            m = calc_metrics(equity_series, trades, initial_cash, bars_per_year=None)
            out.append({
                "score": round(_balance_score(m), 6),
                "total_return": round(float(m["total_return"]), 6),
                "max_loss": round(float(m["max_loss"]), 6),
                "status": "ok",
            })
        except Exception as exc:  # noqa: BLE001 — a variant may not fit a window
            logger.debug("sensitivity: %s failed on window %s: %s", name, w["label"], exc)
            out.append({"status": "failed"})
    return out


def _mean_score(cells: List[Optional[Dict[str, Any]]]) -> Optional[float]:
    ok = [c["score"] for c in cells if c and c.get("status") == "ok"]
    return round(float(np.mean(ok)), 6) if ok else None


def _param_sensitivity(
    strategies: List[Dict[str, Any]],
    strategy_specs: List[Dict[str, Any]],
    holdings: List[PaperHolding],
    data_map: Dict[str, pd.DataFrame],
    windows: List[Dict[str, Any]],
    initial_cash: float,
    bh_cells: Optional[List[Optional[Dict[str, Any]]]],
) -> List[Dict[str, Any]]:
    """±25% one-at-a-time perturbation of the top strategies' key parameters.

    The multi-window test guards against era luck and the baseline guards
    against rising-tide luck; this guards against parameter luck. Verdict:
    ``robust`` when every perturbed variant's mean balance score still beats
    buy & hold's, ``sensitive`` when any falls below, ``no_params`` for
    cadence-only strategies.
    """
    params_by_name = {s["name"]: dict(s.get("params") or {}) for s in strategy_specs}
    bh_score = _mean_score(bh_cells) if bh_cells is not None else None

    results: List[Dict[str, Any]] = []
    for row in strategies[:_ENSEMBLE_SIZE]:
        name = row["name"]
        specs = _PERTURB_SPECS.get(name, [])
        if not specs:
            results.append({
                "name": name, "verdict": "no_params", "base_score": row.get("mean_score"),
                "variants": [], "worst_score": None,
            })
            continue
        base_params = params_by_name.get(name, {})
        variants: List[Dict[str, Any]] = []
        for param, default in specs:
            base_value = base_params.get(param, default)
            for factor in _PERTURB_FACTORS:
                value = _perturbed_value(base_value, factor)
                cells = _evaluate_over_windows(
                    holdings, data_map, name, {**base_params, param: value},
                    windows, initial_cash,
                )
                score = _mean_score(cells)
                variants.append({
                    "param": param,
                    "value": value,
                    "mean_score": score,
                    "beats_hold": (
                        None if score is None or bh_score is None else bool(score > bh_score)
                    ),
                })
        scores = [v["mean_score"] for v in variants if v["mean_score"] is not None]
        worst = min(scores) if scores else None
        if not scores:
            verdict = "sensitive"  # every variant failed to run — that IS fragility
        elif bh_score is not None:
            verdict = "robust" if worst > bh_score else "sensitive"
        else:
            base = row.get("mean_score")
            verdict = "robust" if base is not None and worst >= base - abs(base) * 0.5 else "sensitive"
        results.append({
            "name": name, "verdict": verdict, "base_score": row.get("mean_score"),
            "variants": variants, "worst_score": worst,
        })
    return results


def _build_ensemble(
    strategies: List[Dict[str, Any]],
    cells: Dict[str, List[Optional[Dict[str, Any]]]],
    curves: Dict[tuple, pd.Series],
    windows: List[Dict[str, Any]],
    initial_cash: float,
    bh_cells: Optional[List[Optional[Dict[str, Any]]]],
) -> Optional[Dict[str, Any]]:
    """Equal-capital blend of the top-k mean-rank strategies.

    Per window, each member's equity curve (run with the full ``initial_cash``)
    is scaled by 1/k and summed — equivalent to splitting the capital, since
    both engines charge percentage-based costs and allow fractional sizing.
    Windows where any member failed are marked failed for the blend.
    """
    members = [s["name"] for s in strategies[:_ENSEMBLE_SIZE] if s["ok_count"] > 0]
    if len(members) < 2:
        return None

    k = len(members)
    ens_cells: List[Optional[Dict[str, Any]]] = []
    for wi in range(len(windows)):
        member_curves = [curves.get((name, wi)) for name in members]
        if any(c is None or len(c) < 2 for c in member_curves):
            ens_cells.append({"status": "failed"})
            continue
        union_index = member_curves[0].index
        for c in member_curves[1:]:
            union_index = union_index.union(c.index)
        combined = sum(
            c.reindex(union_index).ffill().fillna(initial_cash) for c in member_curves
        ) / k
        m = calc_metrics(combined, [], initial_cash, bars_per_year=None)
        ens_cells.append({
            "score": round(_balance_score(m), 6),
            "total_return": round(float(m["total_return"]), 6),
            "max_loss": round(float(m["max_loss"]), 6),
            "status": "ok",
        })

    ok_cells = [c for c in ens_cells if c and c.get("status") == "ok"]
    if not ok_cells:
        return None
    mean_score = round(float(np.mean([c["score"] for c in ok_cells])), 6)
    winner_score = strategies[0].get("mean_score")
    return {
        "members": members,
        "cells": ens_cells,
        "ok_count": len(ok_cells),
        "mean_score": mean_score,
        "mean_return": round(float(np.mean([c["total_return"] for c in ok_cells])), 6),
        "mean_max_loss": round(float(np.mean([c["max_loss"] for c in ok_cells])), 6),
        "beats_winner": bool(winner_score is not None and mean_score > winner_score),
        "mean_excess_vs_hold": (
            _mean_excess_vs_cells(ens_cells, bh_cells) if bh_cells is not None else None
        ),
        "windows_beating_hold": (
            _windows_beating(ens_cells, bh_cells) if bh_cells is not None else None
        ),
    }


def run_robust_optimize(
    holdings: List[PaperHolding],
    start_date: str | None,
    end_date: str,
    initial_cash: float,
    strategy_specs: List[Dict[str, Any]],
    window_years: int = 3,
    step_years: int = 1,
) -> Dict[str, Any]:
    """Evaluate every strategy across rolling windows; rank by average rank.

    ``strategy_specs`` is a list of ``{"name": str, "params": dict}``.
    Returns a matrix-friendly payload plus the average-rank winner.
    """
    from backtest.loaders.yfinance_loader import DataLoader as YFinanceLoader

    equity_holdings = [h for h in holdings if h.symbol.upper() != "CASH"]
    if not equity_holdings:
        raise ValueError("Portfolio has no equity holdings — only cash")

    codes = [_to_code(h) for h in equity_holdings]
    fetch_start = _history_start_date(end_date)
    data_map = YFinanceLoader().fetch(codes, fetch_start, end_date, interval="1D")
    if not data_map:
        raise ValueError("No price data fetched — check symbols and date range")

    span_start, span_end, limiting_symbols = _common_data_span(data_map, codes)
    data_map = {code: data_map[code].loc[span_start:span_end] for code in codes}

    windows = _build_windows(span_start, span_end, window_years, step_years)

    # cell[strategy_name][window_idx] = {score, total_return, max_loss, status}
    cells: Dict[str, List[Optional[Dict[str, Any]]]] = {
        spec["name"]: [None] * len(windows) for spec in strategy_specs
    }
    # Equity curves kept per (strategy, window) so the top-k ensemble can be
    # built by summing scaled curves instead of re-running the backtests.
    curves: Dict[tuple, pd.Series] = {}

    for wi, w in enumerate(windows):
        sliced = {
            c: df.loc[w["start"]:w["end"]]
            for c, df in data_map.items()
        }
        sliced = {c: df for c, df in sliced.items() if df is not None and len(df) >= 2}
        for spec in strategy_specs:
            name, params = spec["name"], spec.get("params", {})
            try:
                if not sliced:
                    raise ValueError("No data in window")
                equity_series, trades = evaluate_strategy(
                    equity_holdings, sliced, name, params, initial_cash,
                )
                if equity_series is None or len(equity_series) < 2:
                    raise ValueError("Empty equity curve")
                m = calc_metrics(equity_series, trades, initial_cash, bars_per_year=None)
                cells[name][wi] = {
                    "score": round(_balance_score(m), 6),
                    "total_return": round(float(m["total_return"]), 6),
                    "max_loss": round(float(m["max_loss"]), 6),
                    "status": "ok",
                }
                curves[(name, wi)] = equity_series.astype(float)
            except Exception as exc:  # noqa: BLE001 — a strategy may not fit a window
                logger.debug("robust: %s failed on window %s: %s", name, w["label"], exc)
                cells[name][wi] = {"status": "failed"}

    # Rank within each window (1 = best by balance score). Failed cells get the
    # worst rank for that window so chronic failures are penalised.
    n_strats = len(strategy_specs)
    for wi in range(len(windows)):
        scored = [
            (spec["name"], cells[spec["name"]][wi])
            for spec in strategy_specs
            if cells[spec["name"]][wi] and cells[spec["name"]][wi]["status"] == "ok"
        ]
        scored.sort(key=lambda kv: kv[1]["score"], reverse=True)
        for rank, (name, cell) in enumerate(scored, start=1):
            cell["rank"] = rank
        worst = len(scored) + 1
        for spec in strategy_specs:
            cell = cells[spec["name"]][wi]
            if cell and cell.get("status") == "ok":
                continue
            cells[spec["name"]][wi] = {**(cell or {"status": "failed"}), "rank": worst}

    strategies: List[Dict[str, Any]] = []
    for spec in strategy_specs:
        name = spec["name"]
        row = cells[name]
        ranks = [c["rank"] for c in row if c and "rank" in c]
        ok_cells = [c for c in row if c and c.get("status") == "ok"]
        ok_count = len(ok_cells)
        mean_rank = float(np.mean(ranks)) if ranks else float(n_strats)
        worst_rank = int(max(ranks)) if ranks else n_strats
        rank_std = float(np.std(ranks)) if len(ranks) > 1 else 0.0
        mean_score = float(np.mean([c["score"] for c in ok_cells])) if ok_cells else float("-inf")
        mean_return = float(np.mean([c["total_return"] for c in ok_cells])) if ok_cells else 0.0
        mean_loss = float(np.mean([c["max_loss"] for c in ok_cells])) if ok_cells else 0.0
        strategies.append({
            "name": name,
            "cells": row,
            "mean_rank": round(mean_rank, 3),
            "worst_rank": worst_rank,
            "rank_std": round(rank_std, 3),
            "ok_count": ok_count,
            "mean_score": None if mean_score == float("-inf") else round(mean_score, 6),
            "mean_return": round(mean_return, 6),
            "mean_max_loss": round(mean_loss, 6),
        })

    # Winner: lowest average rank, tiebreak by lowest worst-rank, then highest
    # mean balance score.
    def sort_key(s: Dict[str, Any]):
        return (s["mean_rank"], s["worst_rank"], -(s["mean_score"] if s["mean_score"] is not None else -1e9))

    strategies.sort(key=sort_key)
    best_name = strategies[0]["name"] if strategies else None

    # ── Buy & hold baseline (direction: honest yardstick) ──────────────────
    # Every strategy row gains its mean excess return over buy & hold and the
    # number of windows in which it actually beat holding, so a "winner" that
    # merely rode the underlying's rise is visible as such.
    bh_cells = cells.get(_BASELINE_STRATEGY)
    baseline = None
    if bh_cells is not None:
        bh_row = next((s for s in strategies if s["name"] == _BASELINE_STRATEGY), None)
        if bh_row is not None:
            baseline = {
                "name": _BASELINE_STRATEGY,
                "mean_rank": bh_row["mean_rank"],
                "mean_return": bh_row["mean_return"],
                "mean_max_loss": bh_row["mean_max_loss"],
                "mean_score": bh_row["mean_score"],
            }
        for s in strategies:
            s["mean_excess_vs_hold"] = _mean_excess_vs_cells(cells[s["name"]], bh_cells)
            s["windows_beating_hold"] = _windows_beating(cells[s["name"]], bh_cells)

    # ── Top-k equal-capital ensemble (direction: dampen selection luck) ────
    # Picking the argmax of ~30 candidates on shared data overstates the
    # winner. Splitting capital equally across the top-k mean-rank strategies
    # trades a little peak performance for much lower selection variance. The
    # blend is the scaled sum of member equity curves — engines cost
    # percentage-wise, so curves are linear in starting cash.
    ensemble = _build_ensemble(
        strategies, cells, curves, windows, initial_cash, bh_cells,
    )

    # ── ±25% parameter sensitivity (direction: dampen parameter luck) ──────
    param_sensitivity = _param_sensitivity(
        strategies, strategy_specs, equity_holdings, data_map, windows,
        initial_cash, bh_cells,
    )

    return {
        "windows": [
            {"label": w["label"], "start": w["start"].strftime("%Y-%m-%d"),
             "end": w["end"].strftime("%Y-%m-%d"), "is_full": w["is_full"]}
            for w in windows
        ],
        "strategies": strategies,
        "best_strategy": best_name,
        "baseline": baseline,
        "ensemble": ensemble,
        "param_sensitivity": param_sensitivity,
        "window_years": window_years,
        "step_years": step_years,
        "data_start": span_start.strftime("%Y-%m-%d"),
        "data_end": span_end.strftime("%Y-%m-%d"),
        "limiting_symbols": limiting_symbols,
        "history_cap_years": _MAX_HISTORY_YEARS,
    }
