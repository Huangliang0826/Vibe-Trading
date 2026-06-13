"""Look-ahead sentinel for arbitrary ``SignalEngine`` implementations.

The factor zoo has a per-alpha look-ahead guard (``tests/factors/test_lookahead.py``),
but a *generated* ``SignalEngine`` computes its own factors/IC/weights inline and
never touches the registry — so it bypasses that guard entirely. This module
catches look-ahead in the engine itself, at the ``generate(data_map)`` seam the
runner uses.

Principle — **corrupt the future, check the past**:

  1. Run the engine on the real panel; snapshot the signal series.
  2. Destroy every OHLCV value at rows ``>= cutoff`` (default: last 20% of each
     series) with NaNs / absurd values.
  3. Re-run the engine and compare the signals on rows ``< cutoff``.

A signal at row ``t < cutoff`` may only depend on data at rows ``<= t`` — all of
which are untouched. So for an honest engine the pre-cutoff signals are bit-for-bit
invariant. If any pre-cutoff signal changes, the engine read a row ``>= cutoff``
to produce it: a look-ahead leak. The classic ``fwd = close.shift(-5)`` /
``rolling(60).corr(fwd)`` IC bug trips this at the rows just below ``cutoff``,
whose 5-day forward window reaches into the poisoned tail.

This is intentionally engine-agnostic: it only assumes the documented contract
``generate(data_map: dict[str, DataFrame]) -> dict[str, Series]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# OHLCV columns we poison. A column the engine doesn't read is simply a no-op.
_PRICE_COLS = ("open", "high", "low", "close", "volume", "amount", "vwap")
_ABSURD = 1e10


@dataclass
class CodeLeak:
    """One symbol whose pre-cutoff signal moved after the future was corrupted."""

    code: str
    n_diff: int           # number of pre-cutoff bars that changed
    first_diff: str       # ISO date of the earliest changed bar
    max_abs_diff: float   # largest finite signal delta (NaN-flip reported as inf)


@dataclass
class LookaheadReport:
    leaked: bool
    cutoff_frac: float
    checked_codes: list[str] = field(default_factory=list)
    skipped_codes: list[str] = field(default_factory=list)
    leaks: list[CodeLeak] = field(default_factory=list)

    def summary(self) -> str:
        if not self.leaked:
            n = len(self.checked_codes)
            return f"no look-ahead detected ({n} symbol(s) checked, cutoff={self.cutoff_frac:.0%})"
        lines = [f"LOOK-AHEAD DETECTED — {len(self.leaks)} symbol(s) leak future data:"]
        for lk in self.leaks:
            mag = "NaN-flip" if not np.isfinite(lk.max_abs_diff) else f"max|Δ|={lk.max_abs_diff:.3g}"
            lines.append(
                f"  • {lk.code}: {lk.n_diff} pre-cutoff bar(s) changed when rows after the "
                f"cutoff were corrupted (first at {lk.first_diff}, {mag})"
            )
        lines.append(
            "  A signal before the cutoff must not depend on prices after it. The usual cause "
            "is a forward return (e.g. close.shift(-N)) fed into an IC/weight without being lagged."
        )
        return "\n".join(lines)


def _nan_equal(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Element-wise equality treating NaN==NaN as True (rtol/atol=1e-9 otherwise)."""
    both_nan = np.isnan(a) & np.isnan(b)
    close = np.isclose(a, b, rtol=1e-9, atol=1e-9, equal_nan=False)
    return both_nan | close


def _corrupt_tail(
    data_map: dict[str, pd.DataFrame], cutoff_frac: float
) -> dict[str, pd.DataFrame]:
    """Deep-copy ``data_map`` and poison every price column at rows >= per-code cutoff.

    Even-indexed symbols get NaN; odd-indexed get an absurd finite value — so both
    representations of "garbage future" exercise the engine.
    """
    out: dict[str, pd.DataFrame] = {}
    for j, (code, df) in enumerate(data_map.items()):
        clone = df.copy()
        cutoff = int(len(clone) * cutoff_frac)
        poison = np.nan if j % 2 == 0 else _ABSURD
        for col in clone.columns:
            if str(col).lower() in _PRICE_COLS:
                clone.iloc[cutoff:, clone.columns.get_loc(col)] = poison
        out[code] = clone
    return out


def detect_lookahead(
    engine, data_map: dict[str, pd.DataFrame], *, cutoff_frac: float = 0.8
) -> LookaheadReport:
    """Run ``engine.generate`` on clean and future-corrupted panels; flag leaks.

    Args:
        engine: an instantiated SignalEngine with ``generate(data_map)``.
        data_map: code -> OHLCV DataFrame (index=date). Used as-is, so the test
            reflects exactly the data the engine will run on.
        cutoff_frac: fraction of each series kept clean; rows after it are poisoned.

    Returns:
        LookaheadReport. ``report.leaked`` is True iff some symbol's pre-cutoff
        signal changed under future corruption.
    """
    if not 0.0 < cutoff_frac < 1.0:
        raise ValueError(f"cutoff_frac must be in (0,1), got {cutoff_frac}")

    baseline = engine.generate({k: v.copy() for k, v in data_map.items()})
    corrupted = engine.generate(_corrupt_tail(data_map, cutoff_frac))

    report = LookaheadReport(leaked=False, cutoff_frac=cutoff_frac)
    for code, df in data_map.items():
        cutoff = int(len(df) * cutoff_frac)
        if cutoff < 2:
            report.skipped_codes.append(code)
            continue
        b = baseline.get(code)
        c = corrupted.get(code)
        if b is None or c is None:
            report.skipped_codes.append(code)
            continue
        idx = df.index[:cutoff]
        bb = b.reindex(df.index).iloc[:cutoff].to_numpy(dtype=np.float64)
        cc = c.reindex(df.index).iloc[:cutoff].to_numpy(dtype=np.float64)
        report.checked_codes.append(code)

        diff_mask = ~_nan_equal(bb, cc)
        if diff_mask.any():
            finite = np.isfinite(bb) & np.isfinite(cc)
            deltas = np.abs(bb[finite & diff_mask] - cc[finite & diff_mask])
            max_abs = float(deltas.max()) if deltas.size else float("inf")  # only NaN-flips
            first = pd.Timestamp(idx[int(np.argmax(diff_mask))])
            report.leaks.append(
                CodeLeak(code=code, n_diff=int(diff_mask.sum()),
                         first_diff=str(first.date()), max_abs_diff=max_abs)
            )
    report.leaked = bool(report.leaks)
    return report
