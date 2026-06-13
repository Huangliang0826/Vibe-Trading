"""Integration test: the runner's look-ahead pre-flight gate (backtest/runner.py).

Drives ``runner.main`` end-to-end with the data fetch mocked, asserting that a
generated SignalEngine with a forward-return leak is rejected with a non-zero
exit BEFORE any backtest runs, while an honest engine passes the gate and
reaches the backtest engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import backtest.runner as runner


# --- two engines written to disk as the run's code/signal_engine.py -----------

_HONEST_ENGINE = '''
import numpy as np
import pandas as pd


class SignalEngine:
    def generate(self, data_map):
        out = {}
        for code, df in data_map.items():
            close = df["close"]
            mom = np.log(close / close.shift(20))
            sig = pd.Series(0.0, index=df.index)
            sig[mom > 0.05] = 1.0
            sig[mom < -0.05] = -1.0
            out[code] = sig.fillna(0.0)
        return out
'''

_LEAKY_ENGINE = '''
import numpy as np
import pandas as pd


class SignalEngine:
    def generate(self, data_map):
        out = {}
        for code, df in data_map.items():
            close = df["close"]
            z = (close - close.rolling(60).mean()) / close.rolling(60).std()
            fwd = np.log(close.shift(-5) / close)          # forward return -> leak
            ic = z.rolling(60).corr(fwd)
            composite = (z * np.sign(ic)).fillna(0.0)
            sig = pd.Series(0.0, index=df.index)
            sig[composite > 0.3] = 1.0
            sig[composite < -0.3] = -1.0
            out[code] = sig.fillna(0.0)
        return out
'''


def _panel(n: int = 400, n_syms: int = 4, seed: int = 3) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    data = {}
    for i in range(n_syms):
        close = np.abs(100.0 + np.cumsum(rng.normal(0.05, 1.0, size=n))) + 5.0
        data[f"AAA{i}.US"] = pd.DataFrame(
            {"open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": rng.integers(1e3, 1e5, n).astype(float)},
            index=idx,
        )
    return data


def _make_run_dir(tmp_path: Path, engine_src: str) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "code" / "signal_engine.py").write_text(engine_src, encoding="utf-8")
    config = {
        "codes": [f"AAA{i}.US" for i in range(4)],
        "start_date": "2024-01-01",
        "end_date": "2025-06-01",
        "source": "auto",
        "interval": "1D",
        "engine": "daily",
    }
    (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return run_dir


@pytest.fixture
def _wired(tmp_path, monkeypatch):
    """Allow the tmp run root and mock the data fetch; return the panel."""
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    panel = _panel()
    monkeypatch.setattr(runner, "_fetch_auto", lambda codes, config, interval="1D": panel)
    return panel


def test_leaky_engine_is_blocked(tmp_path, monkeypatch, capsys, _wired):
    run_dir = _make_run_dir(tmp_path, _LEAKY_ENGINE)

    # If the gate failed to fire, the run would proceed into the engine — make
    # that loud rather than silently passing.
    def _boom(*a, **k):
        raise AssertionError("backtest ran — look-ahead gate did NOT block the leaky engine")

    monkeypatch.setattr(runner, "_create_market_engine", _boom)

    with pytest.raises(SystemExit) as exc:
        runner.main(run_dir)
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload.get("error") == "look-ahead detected"
    assert "LOOK-AHEAD DETECTED" in payload.get("detail", "")


def test_honest_engine_passes_gate(tmp_path, monkeypatch, _wired):
    run_dir = _make_run_dir(tmp_path, _HONEST_ENGINE)

    reached = {"ran": False}

    class _StubEngine:
        def run_backtest(self, *a, **k):
            reached["ran"] = True

    monkeypatch.setattr(runner, "_create_market_engine", lambda *a, **k: _StubEngine())

    runner.main(run_dir)  # must NOT raise SystemExit
    assert reached["ran"], "honest engine was blocked or never reached the backtest"
