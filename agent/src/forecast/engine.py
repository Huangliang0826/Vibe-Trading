"""TimesFM 2.5 inference wrapper: a lazy, process-global singleton.

Loading the checkpoint is slow (tens of seconds) and memory-heavy, so the model
is loaded once on first use and reused. Inference itself is fast (~0.2s/series).
TimesFM is an *optional* dependency: if it is not installed, :func:`forecast`
raises ``TimesFMUnavailable`` which callers translate into a graceful API
response (baselines still work without it).
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# TimesFM 2.5 quantile head emits 10 columns per step: index 0 is the point
# (mean) forecast; indices 1..9 are quantiles q10..q90.
_Q10_COL, _Q50_COL, _Q90_COL = 1, 5, 9

# Compile-time ceiling on context length. The model is compiled once for up to
# this many input steps; per-request ``context`` (see ``forecast``) can ask for
# fewer, but never more than this without a costly recompile. ~3650 trading days
# (~14y) comfortably covers "use all available history" for any liquid name.
_MAX_CONTEXT = 3650
_MAX_HORIZON = 256


def resolve_context(n_available: int, context: int | None) -> int:
    """How many trailing points to actually feed the model.

    ``context`` <= 0 or ``None`` means "use everything available" (capped at the
    compiled ceiling). A positive value is clamped to ``[32, ceiling, available]``.
    """
    ceiling = min(_MAX_CONTEXT, n_available)
    if context and context > 0:
        return max(32, min(context, ceiling))
    return ceiling


class TimesFMUnavailable(RuntimeError):
    """Raised when the optional ``timesfm`` dependency is not importable."""


_model = None
_model_lock = threading.Lock()


def _load_model():
    """Load (once) and return the compiled TimesFM 2.5 model singleton."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:  # double-checked under lock
            return _model
        try:
            import timesfm
        except Exception as exc:  # noqa: BLE001
            raise TimesFMUnavailable(
                "timesfm is not installed; run `pip install 'timesfm[torch]'`"
            ) from exc
        logger.info("loading TimesFM 2.5 200M checkpoint (first call is slow)…")
        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            timesfm.TimesFM_2p5_200M_torch.DEFAULT_REPO_ID
        )
        model.compile(
            timesfm.ForecastConfig(
                max_context=_MAX_CONTEXT,
                max_horizon=_MAX_HORIZON,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
                fix_quantile_crossing=True,
            )
        )
        _model = model
        logger.info("TimesFM ready")
        return _model


def is_available() -> bool:
    """True if ``timesfm`` can be imported (does not load the checkpoint)."""
    try:
        import timesfm  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def forecast(
    closes: list[float], horizon: int, context: int | None = None
) -> dict[str, list[float]]:
    """Forecast ``horizon`` steps ahead from a 1-D ``closes`` series.

    ``context`` controls how many trailing history points feed the model
    (``None``/<=0 = use all available, capped at the compiled ceiling). The
    returned dict includes ``context_used`` so callers can report it.
    Raises :class:`TimesFMUnavailable` if the optional dependency is missing.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if horizon > _MAX_HORIZON:
        horizon = _MAX_HORIZON
    arr = np.asarray(closes, dtype=np.float32)
    arr = arr[np.isfinite(arr)]
    if arr.size < 32:
        raise ValueError(f"need >=32 history points, got {arr.size}")
    k = resolve_context(arr.size, context)
    arr = arr[-k:]

    model = _load_model()
    point, quant = model.forecast(horizon=horizon, inputs=[arr])
    point = np.asarray(point)[0]      # (horizon,)
    quant = np.asarray(quant)[0]      # (horizon, 10)
    return {
        "point": [float(x) for x in point],
        "p10": [float(x) for x in quant[:, _Q10_COL]],
        "p50": [float(x) for x in quant[:, _Q50_COL]],
        "p90": [float(x) for x in quant[:, _Q90_COL]],
        "context_used": int(k),
    }
