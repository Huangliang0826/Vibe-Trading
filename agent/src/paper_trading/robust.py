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

    return {
        "windows": [
            {"label": w["label"], "start": w["start"].strftime("%Y-%m-%d"),
             "end": w["end"].strftime("%Y-%m-%d"), "is_full": w["is_full"]}
            for w in windows
        ],
        "strategies": strategies,
        "best_strategy": best_name,
        "window_years": window_years,
        "step_years": step_years,
        "data_start": span_start.strftime("%Y-%m-%d"),
        "data_end": span_end.strftime("%Y-%m-%d"),
        "limiting_symbols": limiting_symbols,
        "history_cap_years": _MAX_HISTORY_YEARS,
    }
