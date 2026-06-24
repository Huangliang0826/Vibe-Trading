"""Walk-forward calibration: does TimesFM actually beat the naive baseline?

For each historical cutoff we forecast ``bt_horizon`` trading days ahead from the
data available at that point, then compare the prediction to what really
happened. We report directional hit-rate, mean absolute error vs the naive
random-walk and drift baselines, and the empirical coverage of the 80% cone.

The honest expectation for equities: directional accuracy hovers near 50% and
MAE skill over the random walk is small or negative. Surfacing that *is* the
value of this view.
"""
from __future__ import annotations

import logging
import math

import numpy as np

from src.forecast import baselines, engine

logger = logging.getLogger(__name__)

DEFAULT_BT_HORIZON = 63   # ~3 trading months — matches the 3-month forecast.
                          # Shorter horizon → folds overlap less → more
                          # independent samples → more trustworthy statistics.


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


# z-score for the 90th percentile → the half-width of a Normal 80% central
# interval (p10..p90). Used to build the naive "random walk + historical vol" band.
_Z80 = 1.2815515594


def _interval_score(lower: float, upper: float, y: float, alpha: float = 0.2) -> float:
    """Winkler interval score for a central (1-α) interval. Lower = better.

    Combines sharpness (width) and calibration (miss penalty, scaled by 2/α) into
    one number; minimized only by the true quantiles, so it can't be gamed by
    widening or narrowing the band.
    """
    width = upper - lower
    penalty = 0.0
    if y < lower:
        penalty = (2.0 / alpha) * (lower - y)
    elif y > upper:
        penalty = (2.0 / alpha) * (y - upper)
    return width + penalty


def _naive_interval(ctx: np.ndarray, start_price: float, horizon: int) -> tuple[float, float]:
    """Random-walk + historical-vol 80% band for the terminal price.

    σ from daily log-returns over the context, scaled by √horizon — the free
    probabilistic baseline the model's interval must beat to add value.
    """
    if ctx.size < 3 or start_price <= 0:
        return start_price, start_price
    rets = np.diff(np.log(ctx[ctx > 0]))
    sigma = float(np.std(rets)) if rets.size else 0.0
    band = _Z80 * sigma * math.sqrt(horizon)
    return start_price * math.exp(-band), start_price * math.exp(band)


def _conformal(p10s, p90s, ys, alpha: float = 0.2, window: int | None = None) -> dict | None:
    """Adaptive (rolling-window) Conformalized Quantile Regression.

    Plain split-CQR assumes exchangeability, which fails on equities — when the
    test period is more volatile than the calibration period a static Q under-
    covers. So we recalibrate Q from a *trailing window* of recent conformity
    scores at every step, which tracks the current volatility regime (the
    practical adaptive-conformal recipe, cf. Gibbs & Candès 2021).

    Conformity score (Romano et al. 2019): E_i = max(p10_i - y_i, y_i - p90_i).
    Reports raw vs conformal coverage + width over the evaluated tail, plus the
    most recent Q (``q_last``) for drawing the live conformal band.
    """
    n = len(ys)
    if n < 16:
        return None
    lo = np.asarray(p10s, float); hi = np.asarray(p90s, float); y = np.asarray(ys, float)
    w = window or min(16, n // 2)

    raw_cov, conf_cov, raw_w, conf_w, qs = [], [], [], [], []
    for i in range(w, n):
        e = np.maximum(lo[i - w:i] - y[i - w:i], y[i - w:i] - hi[i - w:i])
        k = min(max(int(np.ceil((w + 1) * (1 - alpha))), 1), w)
        q = float(np.sort(e)[k - 1])
        qs.append(q)
        raw_cov.append(bool(lo[i] <= y[i] <= hi[i]))
        conf_cov.append(bool((lo[i] - q) <= y[i] <= (hi[i] + q)))
        raw_w.append(hi[i] - lo[i])
        conf_w.append((hi[i] + q) - (lo[i] - q))
    if not raw_cov:
        return None
    rw, cw = float(np.mean(raw_w)), float(np.mean(conf_w))
    return {
        "method": "rolling", "window": w, "target": 1 - alpha,
        "q": float(np.mean(qs)), "q_last": qs[-1], "n_test": len(raw_cov),
        "coverage_raw": float(np.mean(raw_cov)),
        "coverage_conformal": float(np.mean(conf_cov)),
        "width_raw": rw, "width_conformal": cw,
        "width_ratio": (cw / rw) if rw > 0 else None,
    }


def calibration(
    bars: list[dict],
    bt_horizon: int = DEFAULT_BT_HORIZON,
    context: int | None = None,
    step: int = 10,
    max_folds: int = 40,
) -> dict:
    """Run a walk-forward backtest over ``bars`` (daily closes).

    ``context`` controls how much trailing history each fold feeds the model —
    the SAME knob as the live forecast, so the backtest stays representative
    (``None``/<=0 = use all available up to the compiled ceiling).

    Returns aggregate metrics plus one representative predicted-vs-realized
    overlay (most recent fold) for plotting. Raises nothing for the missing-
    model case — instead reports ``model_available=False`` and baseline-only
    stats.
    """
    clean = [
        b for b in bars
        if b.get("close") is not None and math.isfinite(float(b["close"]))
    ]
    closes = np.asarray([float(b["close"]) for b in clean], dtype=float)
    dates = [str(b["date"]) for b in clean]
    n = closes.size

    model_ok = engine.is_available()
    min_needed = 64 + bt_horizon
    if n < min_needed:
        return {
            "model_available": model_ok,
            "n_folds": 0,
            "bt_horizon": bt_horizon,
            "error": "insufficient_history",
        }

    # Cutoffs: forecast from index t, evaluate against closes[t : t+bt_horizon].
    first_t = max(64, n - max_folds * step - bt_horizon)
    cutoffs = list(range(first_t, n - bt_horizon, step))
    if not cutoffs:
        return {"model_available": model_ok, "n_folds": 0,
                "bt_horizon": bt_horizon, "error": "no_folds"}

    model_dir_hits = drift_dir_hits = dir_total = 0
    ae_model, ae_rw, ae_drift = [], [], []
    cover_hits = cover_total = 0
    is_model, is_naive, width_pct = [], [], []  # interval score + sharpness
    cqr_lo, cqr_hi, cqr_y = [], [], []          # per-fold terminal band for CQR
    overlay = None

    ctx_used = 0
    for t in cutoffs:
        ctx_len = engine.resolve_context(t, context)
        ctx_used = ctx_len
        ctx = closes[max(0, t - ctx_len):t]
        start_price = closes[t - 1]
        realized = closes[t:t + bt_horizon]
        realized_end = realized[-1]
        real_dir = np.sign(realized_end - start_price)

        rw = baselines.random_walk(ctx.tolist(), bt_horizon)
        dr = baselines.drift(ctx.tolist(), bt_horizon)
        ae_rw.append(abs(rw[-1] - realized_end))
        ae_drift.append(abs(dr[-1] - realized_end))

        # drift directional call
        if real_dir != 0:
            dir_total += 1
            if np.sign(dr[-1] - start_price) == real_dir:
                drift_dir_hits += 1

        if model_ok:
            try:
                fc = engine.forecast(ctx.tolist(), bt_horizon, context=context)
            except Exception as exc:  # noqa: BLE001
                logger.warning("backtest fold forecast failed @%d: %s", t, exc)
                continue
            p50_end = fc["p50"][-1]
            p10_end = fc["p10"][-1]
            p90_end = fc["p90"][-1]
            ae_model.append(abs(p50_end - realized_end))
            if real_dir != 0 and np.sign(p50_end - start_price) == real_dir:
                model_dir_hits += 1
            cover_total += 1
            if p10_end <= realized_end <= p90_end:
                cover_hits += 1
            # Interval score (sharpness + calibration in one number) vs the
            # random-walk + historical-vol naive band, plus the model's band
            # width as a % of price (pure sharpness, for interpretability).
            is_model.append(_interval_score(p10_end, p90_end, realized_end))
            n_lo, n_hi = _naive_interval(ctx, start_price, bt_horizon)
            is_naive.append(_interval_score(n_lo, n_hi, realized_end))
            if start_price > 0:
                width_pct.append((p90_end - p10_end) / start_price * 100.0)
            cqr_lo.append(p10_end); cqr_hi.append(p90_end); cqr_y.append(realized_end)
            # representative overlay = the most recent fold
            if t == cutoffs[-1]:
                fut_idx = list(range(t, t + bt_horizon))
                overlay = {
                    "context_dates": dates[max(0, t - 60):t],
                    "context": [float(x) for x in closes[max(0, t - 60):t]],
                    "future_dates": [dates[i] for i in fut_idx],
                    "realized": [float(x) for x in realized],
                    "p10": fc["p10"], "p50": fc["p50"], "p90": fc["p90"],
                }

    mae_model = float(np.mean(ae_model)) if ae_model else None
    mae_rw = float(np.mean(ae_rw)) if ae_rw else None
    mae_drift = float(np.mean(ae_drift)) if ae_drift else None

    is_model_mean = float(np.mean(is_model)) if is_model else None
    is_naive_mean = float(np.mean(is_naive)) if is_naive else None
    width_pct_mean = float(np.mean(width_pct)) if width_pct else None

    conformal = _conformal(cqr_lo, cqr_hi, cqr_y) if model_ok else None
    if conformal and overlay is not None:
        overlay["q"] = conformal["q_last"]  # lets the chart draw the conformal band

    return {
        "model_available": model_ok,
        "n_folds": len(cutoffs),
        "bt_horizon": bt_horizon,
        "context_used": ctx_used,
        "directional_accuracy": {
            "model": _safe_div(model_dir_hits, dir_total) if model_ok else None,
            "drift": _safe_div(drift_dir_hits, dir_total),
            "n": dir_total,
        },
        "mae": {"model": mae_model, "random_walk": mae_rw, "drift": mae_drift},
        # Positive skill = model beats the random walk on MAE. Usually ~0 or < 0.
        "skill_vs_random_walk": (
            1.0 - _safe_div(mae_model, mae_rw) if (mae_model and mae_rw) else None
        ),
        "interval_coverage_80": (
            _safe_div(cover_hits, cover_total) if cover_total else None
        ),
        # Sharpness + calibration in one number (lower = better), and its skill
        # over the naive vol band: >0 means the model's interval is genuinely
        # "tight AND accurate", not just wide enough to cover.
        "interval_score": {"model": is_model_mean, "random_walk": is_naive_mean},
        "interval_score_skill": (
            1.0 - _safe_div(is_model_mean, is_naive_mean)
            if (is_model_mean and is_naive_mean) else None
        ),
        "mean_interval_width_pct": width_pct_mean,
        # Conformal (CQR) calibration: out-of-sample raw vs guaranteed-coverage band.
        "conformal": conformal,
        "overlay": overlay,
    }
