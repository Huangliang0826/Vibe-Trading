"""Assemble a forecast payload: TimesFM cone + naive baselines + future dates.

Decoupled from the web layer — callers pass in a ``bars`` history (the same
``[{date, close, volume}]`` shape the watchlist history endpoint returns) so the
forecast package never imports the API server.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
from typing import Optional

from src.forecast import baselines, backtest, engine

logger = logging.getLogger(__name__)

# 6 months ≈ 126 trading days. Kept here so route + backtest agree.
DEFAULT_HORIZON = 126


def project_business_days(last_date: str, horizon: int) -> list[str]:
    """Return the next ``horizon`` weekday dates (ISO) after ``last_date``.

    Uses Mon–Fri only; exchange holidays are ignored (acceptable for a forecast
    cone whose x-axis is illustrative, not a settlement calendar).
    """
    try:
        d = dt.date.fromisoformat(last_date[:10])
    except ValueError:
        d = dt.date.today()
    out: list[str] = []
    while len(out) < horizon:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:  # 0=Mon … 4=Fri
            out.append(d.isoformat())
    return out


def build_forecast(
    bars: list[dict],
    horizon: int = DEFAULT_HORIZON,
    with_model: bool = True,
    context: int | None = None,
    display_history: int | None = None,
) -> dict:
    """Build the full forecast payload from a daily-close history.

    Returns history (trimmed), future dates, the TimesFM quantile cone (or
    ``None`` when unavailable), and the random-walk / drift baselines.
    """
    # Keep only bars with a finite close; trailing NaNs (incomplete sessions)
    # would otherwise poison the random-walk baseline.
    bars = [
        b for b in bars
        if b.get("close") is not None and math.isfinite(float(b["close"]))
    ]
    closes = [float(b["close"]) for b in bars]
    if len(closes) < 32:
        return {
            "horizon": horizon,
            "history": bars,
            "future_dates": [],
            "model": None,
            "model_available": engine.is_available(),
            "baselines": {"random_walk": [], "drift": []},
            "error": "insufficient_history",
        }

    last_date = str(bars[-1].get("date", dt.date.today().isoformat()))
    future_dates = project_business_days(last_date, horizon)

    model_block: Optional[dict] = None
    model_error: Optional[str] = None
    context_used: Optional[int] = None
    conformal_q: Optional[float] = None
    if with_model:
        try:
            model_block = engine.forecast(closes, horizon, context=context)
            context_used = model_block.pop("context_used", None)
        except engine.TimesFMUnavailable:
            model_error = "timesfm_not_installed"
        except Exception as exc:  # noqa: BLE001
            logger.warning("TimesFM forecast failed: %s", exc)
            model_error = str(exc)

    if model_block is not None:
        try:
            cal = backtest.calibration(
                bars, bt_horizon=horizon, context=context, step=21, max_folds=20,
            )
            conf = cal.get("conformal")
            if conf and conf.get("q_last") is not None:
                last_price = closes[-1]
                q_raw = conf["q_last"]
                q_rel = q_raw / last_price if last_price > 0 else 0.0
                # Only tighten (q < 0 means model over-covers → band can shrink).
                # When q > 0 the model already under-covers on some folds;
                # widening further would make the display useless.
                if q_rel < 0:
                    q_rel = max(q_rel, -0.15)  # cap shrinkage at 15%
                    conformal_q = round(q_rel, 6)
                    model_block["p10"] = [v * (1 - q_rel) for v in model_block["p10"]]
                    model_block["p90"] = [v * (1 + q_rel) for v in model_block["p90"]]
        except Exception as exc:  # noqa: BLE001
            logger.warning("conformal adjustment skipped: %s", exc)

    # Trim displayed history separately from model input. The page's 1Y/2Y/5Y/ALL
    # knob should visibly change the chart while still allowing the model to use
    # the requested context for its own inference.
    if display_history == 0:
        hist = bars
    elif display_history and display_history > 0:
        hist = bars[-display_history:]
    else:
        hist = bars[-756:]

    return {
        "horizon": horizon,
        "history": hist,
        "future_dates": future_dates,
        "model": model_block,
        "model_available": engine.is_available(),
        "model_error": model_error,
        "conformal_q": conformal_q,
        "context_used": context_used,
        "context_available": len(closes),
        "baselines": {
            "random_walk": baselines.random_walk(closes, horizon),
            "drift": baselines.drift(closes, horizon),
        },
    }
