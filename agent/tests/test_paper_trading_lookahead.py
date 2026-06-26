import pandas as pd

from src.paper_trading.executor import _smart_dca_multiplier
from src.paper_trading.models import PaperHolding, StrategyConfig
from src.paper_trading.strategies import generate_dca, generate_grid, generate_signals


def _price_frame(close_values):
    idx = pd.date_range("2024-01-01", periods=len(close_values), freq="D")
    close = pd.Series(close_values, index=idx, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1_000,
        },
        index=idx,
    )


def test_smart_dca_multiplier_uses_only_prior_closes_for_open_buy():
    df = _price_frame([100.0] * 29 + [50.0])
    ts = df.index[-1]

    multiplier = _smart_dca_multiplier(
        df,
        ts,
        {
            "ma_window": 10,
            "vol_window": 5,
            "min_multiplier": 0.3,
            "max_multiplier": 2.0,
        },
    )

    assert multiplier == 1.0


def test_grid_without_manual_bounds_does_not_depend_on_future_prices():
    holding = PaperHolding(symbol="0700", market="hk", allocation_pct=100)
    baseline = _price_frame([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111])
    changed_future = baseline.copy()
    changed_future.loc[changed_future.index[6]:, "close"] = [200, 220, 240, 260, 280, 300]
    for column in ["open", "high", "low"]:
        changed_future[column] = changed_future["close"]

    params = {"auto_range": False, "grid_count": 5}

    first = generate_grid([holding], {"0700.HK": baseline}, params)["0700.HK"]
    second = generate_grid([holding], {"0700.HK": changed_future}, params)["0700.HK"]

    pd.testing.assert_series_equal(first.iloc[:6], second.iloc[:6])


def test_dca_signal_ramp_does_not_size_steps_from_backtest_end():
    holding = PaperHolding(symbol="0700", market="hk", allocation_pct=100)
    short = _price_frame([100.0] * 12)
    long = _price_frame([100.0] * 36)

    params = {"frequency": "weekly", "steps_to_full": 4}

    short_signal = generate_dca([holding], {"0700.HK": short}, params)["0700.HK"]
    long_signal = generate_dca([holding], {"0700.HK": long}, params)["0700.HK"]

    pd.testing.assert_series_equal(short_signal, long_signal.reindex(short_signal.index))


def test_new_strategy_names_are_accepted_and_generate_bounded_signals():
    holding = PaperHolding(symbol="0700", market="hk", allocation_pct=80)
    df = _price_frame([
        100, 101, 102, 104, 106, 105, 103, 101, 99, 98,
        100, 103, 107, 110, 112, 111, 109, 108, 111, 115,
        118, 116, 113, 111, 114, 117, 121, 123, 120, 118,
        121, 125, 128, 126, 124, 127, 131, 134, 132, 136,
    ])

    for name in [
        "atr_trend_stop",
        "mean_reversion_scaleout",
        "enhanced_dca_trend",
        "breakout_pullback",
    ]:
        StrategyConfig(name=name)
        signal = generate_signals([holding], {"0700.HK": df}, name, {})["0700.HK"]
        assert signal.index.equals(df.index)
        assert signal.min() >= 0
        assert signal.max() <= 0.8
