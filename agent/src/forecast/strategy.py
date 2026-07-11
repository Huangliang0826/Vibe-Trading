"""Forecast-driven trading strategies, honestly backtested vs buy-and-hold.

Two long-only rules, both fed only past data at each rebalance:

* ``band_reversion`` — uses the model's *calibrated interval* (its one good
  output): buy when price has fallen to/below the lead-horizon p10 (cheap
  relative to the forward distribution), sell back to flat when it recovers to
  the median p50.
* ``median_trend`` — follows the *median direction* (the output we already
  showed has no edge): long when p50 sits above price, flat otherwise. Included
  as a comparator that is expected to underperform.

Both are walk-forward simulated with transaction costs and compared to
buy-and-hold via the shared :func:`backtest.metrics.calc_metrics`. The honest
expectation: neither reliably beats buy-and-hold net of costs.
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from backtest.metrics import calc_metrics
from backtest.models import TradeRecord
from src.forecast import engine

logger = logging.getLogger(__name__)

DEFAULT_REBALANCE = 5      # trading days between signal updates (~weekly)
DEFAULT_LEAD = 21          # forecast lead used for signals (~1 month)
DEFAULT_EVAL_DAYS = 756    # ~3y eval window — bounds the forecast count
DEFAULT_COST_BPS = 5.0     # per-side fallback; API callers resolve the real
                           # per-market rate via backtest.costs.per_side_cost_bps
_INITIAL_CASH = 10_000.0
_MIN_HISTORY = 252         # context needed before the eval window starts


def _sig_band(price: float, p10: float, p50: float, cur: int) -> int:
    """Band mean-reversion: buy below p10, exit at/above p50 (long-only)."""
    if cur == 0:
        return 1 if price <= p10 else 0
    return 0 if price >= p50 else 1


def _sig_trend(price: float, p50: float, cur: int, eps: float = 0.005) -> int:
    """Median trend-follow: long while median sits above price (long-only)."""
    if cur == 0:
        return 1 if p50 > price * (1 + eps) else 0
    return 1 if p50 > price else 0


def _simulate(
    pos: np.ndarray, closes: np.ndarray, dates: list, start: int, n: int,
    cost_bps: float, symbol: str,
) -> tuple[pd.Series, list[TradeRecord]]:
    """Walk a 0/1 position array into an equity curve + round-trip trades."""
    cost = cost_bps / 1e4
    eq = _INITIAL_CASH
    cur_dates, cur_vals = [], []
    trades: list[TradeRecord] = []
    prev_pos = 0.0
    entry_price = entry_idx = None

    for i in range(start, n):
        if i > start:  # return from prior day, earned at the prior position
            r = closes[i] / closes[i - 1] - 1.0
            eq *= (1 + prev_pos * r)
        if pos[i] != prev_pos:  # turnover at today's close → pay cost on |Δpos|
            eq *= (1 - cost * abs(pos[i] - prev_pos))
            # Round-trips are recorded on flat↔invested crossings only, so this
            # works for both 0/1 rules and fractional (vol-target) positions.
            was_in, now_in = prev_pos > 0, pos[i] > 0
            if now_in and not was_in:           # entered the market
                entry_price, entry_idx = float(closes[i]), i
            elif was_in and not now_in and entry_price is not None:  # fully exited
                trades.append(_close_trade(symbol, entry_price, float(closes[i]),
                                           dates[entry_idx], dates[i],
                                           entry_idx, i, cost))
                entry_price = entry_idx = None
        cur_dates.append(dates[i])
        cur_vals.append(eq)
        prev_pos = pos[i]

    if entry_price is not None:  # close any dangling long at the last bar
        trades.append(_close_trade(symbol, entry_price, float(closes[n - 1]),
                                   dates[entry_idx], dates[n - 1],
                                   entry_idx, n - 1, cost, reason="end_of_backtest"))

    return pd.Series(cur_vals, index=pd.to_datetime(cur_dates)), trades


def _close_trade(symbol, entry, exit_, t_in, t_out, i_in, i_out, cost, reason="signal"):
    size = _INITIAL_CASH / entry
    commission = (entry + exit_) * size * cost
    pnl = (exit_ - entry) * size - commission
    return TradeRecord(
        symbol=symbol, direction=1, entry_price=entry, exit_price=exit_,
        entry_time=pd.Timestamp(t_in), exit_time=pd.Timestamp(t_out),
        size=size, leverage=1.0, pnl=pnl,
        pnl_pct=pnl / _INITIAL_CASH, exit_reason=reason,
        holding_bars=int(i_out - i_in), commission=commission,
    )


def backtest_strategy(
    bars: list[dict],
    context: int | None = None,
    rebalance: int = DEFAULT_REBALANCE,
    cost_bps: float = DEFAULT_COST_BPS,
    eval_days: int = DEFAULT_EVAL_DAYS,
    lead: int = DEFAULT_LEAD,
) -> dict:
    """Walk-forward backtest both forecast strategies against buy-and-hold."""
    clean = [b for b in bars
             if b.get("close") is not None and math.isfinite(float(b["close"]))]
    closes = np.asarray([float(b["close"]) for b in clean], dtype=float)
    dates = [str(b["date"]) for b in clean]
    n = closes.size
    model_ok = engine.is_available()

    if n < _MIN_HISTORY + lead + 30:
        return {"model_available": model_ok, "error": "insufficient_history",
                "params": {"rebalance": rebalance, "cost_bps": cost_bps,
                           "lead": lead, "eval_days": eval_days}}

    start = max(_MIN_HISTORY, n - eval_days)

    # One forecast per rebalance day feeds BOTH strategies (halves model calls).
    #   median_trend  — forward: long when the lead-ahead median sits above price.
    #   band_reversion — backward-anchored: a forecast made a few days ago
    #     predicted a path for *today*; if today's realized price came in at/below
    #     that path's p10, it's genuinely cheap vs the model's band → buy; exit
    #     when it recovers to the predicted p50. (Comparing today's price to a
    #     *forward* p10 is degenerate — that quantile is always below price.)
    #   vol_target — risk overlay: stay ~fully long, but trim exposure when the
    #     model's band (its calibrated uncertainty) widens above its own trailing
    #     median. Goal is lower drawdown, not higher return — the one place the
    #     model's good output (the interval) genuinely helps.
    pos_band = np.zeros(n)
    pos_trend = np.zeros(n)
    pos_vol = np.zeros(n)
    cur_b = cur_t = 0
    cur_v = 1.0
    widths: list[float] = []
    anchor_t = None
    anchor_p10 = anchor_p50 = None
    if model_ok:
        for i in range(start, n):
            price = float(closes[i])
            # band reversion vs the active (recent) forecast's prediction for today
            if anchor_t is not None:
                k = i - anchor_t  # prediction step (1..lead)
                if 1 <= k <= lead:
                    cur_b = _sig_band(price, anchor_p10[k - 1], anchor_p50[k - 1], cur_b)
            # rebalance: refresh forecast → trend / vol-target signals + new anchor
            if (i - start) % rebalance == 0:
                try:
                    fc = engine.forecast(closes[:i + 1].tolist(), lead, context=context)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("strategy forecast @%d failed: %s", i, exc)
                else:
                    cur_t = _sig_trend(price, fc["p50"][-1], cur_t)
                    anchor_t, anchor_p10, anchor_p50 = i, fc["p10"], fc["p50"]
                    w = (fc["p90"][-1] - fc["p10"][-1]) / price if price > 0 else 0.0
                    widths.append(w)
                    ref = float(np.median(widths[-12:])) if len(widths) >= 3 else w
                    cur_v = float(np.clip(ref / w, 0.0, 1.0)) if w > 0 else 1.0
            pos_band[i] = cur_b
            pos_trend[i] = cur_t
            pos_vol[i] = cur_v

    eq_band, tr_band = _simulate(pos_band, closes, dates, start, n, cost_bps, "STRAT")
    eq_trend, tr_trend = _simulate(pos_trend, closes, dates, start, n, cost_bps, "STRAT")
    eq_vol, tr_vol = _simulate(pos_vol, closes, dates, start, n, cost_bps, "STRAT")

    # Buy-and-hold over the same window (essentially costless benchmark).
    win_close = closes[start:n]
    win_dates = pd.to_datetime(dates[start:n])
    eq_bh = pd.Series(_INITIAL_CASH * win_close / win_close[0], index=win_dates)
    bh_ret = eq_bh.pct_change().fillna(0.0)

    def _m(curve, trades, bench):
        return calc_metrics(curve, trades, _INITIAL_CASH, bars_per_year=252,
                            bench_ret=bench)

    m_band = _m(eq_band, tr_band, bh_ret)
    m_trend = _m(eq_trend, tr_trend, bh_ret)
    m_vol = _m(eq_vol, tr_vol, bh_ret)
    m_bh = _m(eq_bh, [], None)

    def _curve(series):
        return [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in series.items()]

    # Return verdict: did anything beat buy-and-hold on total return, after costs?
    best_excess = max(m_band["total_return"], m_trend["total_return"],
                      m_vol["total_return"]) - m_bh["total_return"]
    beats = best_excess > 0
    # Risk verdict: the overlay's honest goal — less drawdown for comparable return.
    # Calmar = annual_return / |max_drawdown|; >0 improvement means better risk-adjust.
    vol_calmar_better = m_vol["calmar"] > m_bh["calmar"]

    def _trades(records: list[TradeRecord]) -> list[dict]:
        return [
            {"entry_date": t.entry_time.strftime("%Y-%m-%d"),
             "exit_date": t.exit_time.strftime("%Y-%m-%d"),
             "entry_price": round(float(t.entry_price), 4),
             "exit_price": round(float(t.exit_price), 4),
             "pnl_pct": round(float(t.pnl_pct), 4),
             "holding_bars": t.holding_bars,
             "exit_reason": t.exit_reason}
            for t in records
        ]

    return {
        "model_available": model_ok,
        "params": {"rebalance": rebalance, "cost_bps": cost_bps,
                   "lead": lead, "eval_days": eval_days, "n_days": int(n - start)},
        "strategies": {
            "band_reversion": {"metrics": m_band, "equity": _curve(eq_band), "trades": _trades(tr_band)},
            "median_trend": {"metrics": m_trend, "equity": _curve(eq_trend), "trades": _trades(tr_trend)},
            "vol_target": {"metrics": m_vol, "equity": _curve(eq_vol), "trades": _trades(tr_vol)},
        },
        "buy_and_hold": {"metrics": m_bh, "equity": _curve(eq_bh)},
        "beats_buy_and_hold": beats,
        "best_excess_return": best_excess,
        "vol_target_calmar_better": vol_calmar_better,
    }


_STRAT_KEYS = ("band_reversion", "median_trend", "vol_target")


def summarize_robustness(items: list[dict]) -> dict:
    """Aggregate per-name :func:`backtest_strategy` results into a distribution.

    Each ``items`` entry is a ``backtest_strategy`` output augmented with
    ``code``/``name``. Reports, per strategy, the median/mean *excess return vs
    buy-and-hold* and the fraction of names where it beats buy-and-hold — the
    honest test of whether any edge is reproducible rather than single-name luck.
    """
    rows = []
    for it in items:
        if "strategies" not in it:
            continue
        bh = it["buy_and_hold"]["metrics"]
        row = {"code": it.get("code"), "name": it.get("name", it.get("code")),
               "bh_return": bh["total_return"], "bh_max_dd": bh["max_drawdown"]}
        for k in _STRAT_KEYS:
            m = it["strategies"][k]["metrics"]
            row[f"{k}_excess"] = m["total_return"] - bh["total_return"]
            row[f"{k}_max_dd"] = m["max_drawdown"]
            row[f"{k}_calmar"] = m["calmar"]
        rows.append(row)

    def agg(field):
        vals = [r[field] for r in rows]
        if not vals:
            return {"median": None, "mean": None, "pct_positive": None}
        return {"median": float(np.median(vals)), "mean": float(np.mean(vals)),
                "pct_positive": float(np.mean([v > 0 for v in vals]))}

    # vol_target's drawdown win = fraction of names with shallower drawdown than B&H
    dd_better = ([r["vol_target_max_dd"] > r["bh_max_dd"] for r in rows]
                 if rows else [])  # less negative = shallower

    return {
        "n": len(rows),
        "per_name": rows,
        "excess": {k: agg(f"{k}_excess") for k in _STRAT_KEYS},
        "vol_target_dd_better_pct": (float(np.mean(dd_better)) if dd_better else None),
    }
