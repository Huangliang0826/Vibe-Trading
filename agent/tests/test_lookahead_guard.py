"""Tests for the engine-level look-ahead sentinel (``backtest.lookahead_guard``).

Two halves that must BOTH hold, or the guard is useless:

  * It stays silent on honest engines (no false positive).
  * It fires on the exact ``close.shift(-5)`` IC-leak pattern that shipped in a
    generated strategy and survived the factor-zoo guard (no false negative).

The leaky engine here is a faithful, trimmed copy of that generated strategy.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd
import pytest

from backtest.lookahead_guard import detect_lookahead


# ---------------------------------------------------------------- fixtures


def _panel(n: int = 500, n_syms: int = 6, seed: int = 7) -> Dict[str, pd.DataFrame]:
    """Reproducible multi-symbol OHLCV panel (random walk), long enough for 252d windows."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    out: Dict[str, pd.DataFrame] = {}
    for i in range(n_syms):
        close = 100.0 + np.cumsum(rng.normal(0.05, 1.0, size=n))
        close = np.abs(close) + 5.0
        open_ = np.concatenate([[close[0]], close[:-1]])
        high = np.maximum(close, open_) + rng.uniform(0, 1, n)
        low = np.minimum(close, open_) - rng.uniform(0, 1, n)
        volume = rng.integers(1_000, 100_000, n).astype(float)
        out[f"SYM{i}"] = pd.DataFrame(
            {"open": open_, "high": high, "low": np.abs(low) + 0.1,
             "close": close, "volume": volume},
            index=idx,
        )
    return out


class HonestEngine:
    """Backward-only multi-factor engine: every input is past data, no forward leak."""

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        signals = {}
        for code, df in data_map.items():
            close, volume = df["close"], df["volume"]
            mom = np.log(close / close.shift(20))
            rev = -np.log(close / close.shift(5))
            vol = -(np.log(close / close.shift(1)).rolling(20).std())
            turn = volume / volume.rolling(20).mean() - 1.0
            composite = mom.fillna(0) + rev.fillna(0) + vol.fillna(0) + turn.fillna(0)
            sig = pd.Series(0.0, index=df.index)
            sig[composite > 0.3] = 1.0
            sig[composite < -0.3] = -1.0
            signals[code] = sig.fillna(0.0)
        return signals


class LeakyEngine:
    """Trimmed copy of the shipped strategy: rolling IC on an UN-lagged forward return."""

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        signals = {}
        for code, df in data_map.items():
            if len(df) < 252:
                signals[code] = pd.Series(0.0, index=df.index)
                continue
            close, volume = df["close"], df["volume"]
            mom = np.log(close / close.shift(20))
            rev = -np.log(close / close.shift(5))
            vol = -(np.log(close / close.shift(1)).rolling(20).std() * np.sqrt(252))
            turn = volume / volume.rolling(20).mean() - 1.0

            def rz(s, w=252):
                return (s - s.rolling(w).mean()) / s.rolling(w).std().replace(0, np.nan)

            z = {"m": rz(mom), "r": rz(rev), "v": rz(vol), "t": rz(turn)}
            fwd = np.log(close.shift(-5) / close)            # <-- the leak
            ic = {k: zk.rolling(60).corr(fwd) for k, zk in z.items()}
            tot = sum(v.abs() for v in ic.values()).replace(0, np.nan)
            composite = sum(
                (ic[k].abs() / tot).fillna(0) * z[k].fillna(0) * np.sign(ic[k].fillna(0))
                for k in z
            )
            sig = pd.Series(0.0, index=df.index)
            sig[composite > 0.3] = 1.0
            sig[composite < -0.3] = -1.0
            signals[code] = sig.fillna(0.0)
        return signals


# ---------------------------------------------------------------- tests


def test_honest_engine_passes() -> None:
    report = detect_lookahead(HonestEngine(), _panel(), cutoff_frac=0.8)
    assert not report.leaked, report.summary()
    assert report.checked_codes, "guard checked no symbols — fixture too short?"


def test_leaky_engine_is_caught() -> None:
    report = detect_lookahead(LeakyEngine(), _panel(), cutoff_frac=0.8)
    assert report.leaked, "sentinel failed to detect the close.shift(-5) IC leak"
    # Leak must surface within the 5-day forward window just below the cutoff.
    assert report.leaks
    assert all(lk.n_diff > 0 for lk in report.leaks)


def test_shipped_multifactor_template_is_clean() -> None:
    """The repo's multi-factor template must itself be look-ahead free."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "src" / "skills" / "multi-factor" / "example_signal_engine.py"
    if not path.exists():
        pytest.skip(f"template not found at {path}")
    spec = importlib.util.spec_from_file_location("_mf_template", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = detect_lookahead(mod.SignalEngine(), _panel(), cutoff_frac=0.8)
    assert not report.leaked, report.summary()
