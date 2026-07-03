import pandas as pd
import pytest

from src.paper_trading.executor import _run_accelerated_entry, _run_dca, _smart_dca_multiplier, evaluate_strategy
from src.paper_trading.models import PaperHolding, StrategyConfig
from src.paper_trading.strategies import generate_dca, generate_grid, generate_signals


def _price_frame(close_values, volume_values=None):
    idx = pd.date_range("2024-01-01", periods=len(close_values), freq="D")
    close = pd.Series(close_values, index=idx, dtype=float)
    volume = pd.Series(volume_values or [1_000] * len(close_values), index=idx, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": volume,
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


def test_dca_then_hold_uses_exactly_three_years_of_monthly_tranches():
    holding = PaperHolding(symbol="AAPL", market="us", allocation_pct=100)
    idx = pd.bdate_range("2020-01-02", "2025-01-02")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1_000},
        index=idx,
    )

    _equity, trades = _run_dca(
        36_000, [holding], {"AAPL.US": frame}, {"frequency": "monthly"}, deploy_years=3,
    )

    assert len(trades) == 36
    assert sum(trade.size for trade in trades) == 360
    StrategyConfig(name="dca_then_hold")


def test_two_year_dca_then_hold_uses_twenty_four_monthly_tranches():
    holding = PaperHolding(symbol="AAPL", market="us", allocation_pct=100)
    idx = pd.bdate_range("2020-01-02", "2023-01-02")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1_000},
        index=idx,
    )

    _equity, trades = evaluate_strategy(
        [holding], {"AAPL.US": frame}, "dca_two_year_then_hold",
        {"frequency": "monthly"}, 240_000,
    )

    assert len(trades) == 24
    assert sum(trade.size for trade in trades) == 2_400
    StrategyConfig(name="dca_two_year_then_hold")


def test_accelerated_entry_deploys_25_percent_then_accelerates_on_drawdowns():
    holding = PaperHolding(symbol="AAPL", market="us", allocation_pct=100)
    idx = pd.bdate_range("2024-01-02", "2024-08-30")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1_000},
        index=idx,
    )
    frame.loc[pd.Timestamp("2024-02-01"), "open"] = 90.0
    frame.loc[pd.Timestamp("2024-03-01"), "open"] = 80.0

    _equity, trades = _run_accelerated_entry(
        100_000, [holding], {"AAPL.US": frame},
        {"initial_pct": 0.25, "n_months": 12, "accelerated_investment_pct": 0.2},
    )

    amounts = [trade.entry_price * trade.size for trade in trades]
    assert len(trades) == 3
    assert amounts[0] == pytest.approx(25_000, abs=1)
    assert amounts[1] == pytest.approx(20_000, abs=1)
    assert amounts[2] == pytest.approx(55_000, abs=1)
    StrategyConfig(name="accelerated_dca_entry")


def test_accelerated_entry_does_not_use_same_day_close_for_open_decision():
    holding = PaperHolding(symbol="AAPL", market="us", allocation_pct=100)
    idx = pd.bdate_range("2024-01-02", "2024-08-30")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1_000},
        index=idx,
    )
    frame.loc[pd.Timestamp("2024-02-01"), ["open", "close"]] = [95.0, 70.0]

    _equity, trades = _run_accelerated_entry(
        100_000, [holding], {"AAPL.US": frame}, {},
    )

    february = next(trade for trade in trades if trade.entry_time == pd.Timestamp("2024-02-01"))
    assert february.entry_price * february.size == pytest.approx(6_250, abs=1)


def test_deep_drawdown_recovery_builds_ten_tranches_and_stages_five_exits():
    holding = PaperHolding(symbol="AAPL", market="us", allocation_pct=100)
    idx = pd.bdate_range("2024-01-02", "2025-03-31")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1_000},
        index=idx,
    )
    drop_day = idx[5]
    first_buy_day = idx[6]
    frame.loc[drop_day:, ["open", "high", "low", "close"]] = 60.0
    take_profit_signal = pd.Timestamp("2024-11-01")
    first_exit = pd.Timestamp("2024-11-04")
    frame.loc[take_profit_signal, ["open", "high", "low", "close"]] = 84.0
    frame.loc[first_exit:, ["open", "high", "low", "close"]] = 70.0
    frame.loc[first_exit, "open"] = 84.0

    _equity, trades = evaluate_strategy(
        [holding], {"AAPL.US": frame}, "deep_drawdown_recovery",
        {
            "drawdown_threshold": 0.4, "take_profit_pct": 0.4,
            "tranches": 10, "exit_tranches": 5, "lookback_years": 3,
        },
        120_000,
    )

    assert len(trades) == 10
    assert trades[0].entry_time == first_buy_day
    assert sorted({trade.exit_time for trade in trades}) == [
        pd.Timestamp("2024-11-04"), pd.Timestamp("2024-12-02"),
        pd.Timestamp("2025-01-01"), pd.Timestamp("2025-02-03"),
        pd.Timestamp("2025-03-03"),
    ]
    assert all(trade.exit_reason == "staged_take_profit_40pct" for trade in trades)
    assert sum(trade.size for trade in trades) == pytest.approx(2_000, abs=0.1)
    StrategyConfig(name="deep_drawdown_recovery")


def test_deep_drawdown_recovery_ignores_peaks_older_than_three_years():
    holding = PaperHolding(symbol="AAPL", market="us", allocation_pct=100)
    idx = pd.bdate_range("2020-01-02", "2024-03-29")
    frame = pd.DataFrame(
        {"open": 80.0, "high": 80.0, "low": 80.0, "close": 80.0, "volume": 1_000},
        index=idx,
    )
    frame.loc[idx[0], ["open", "high", "low", "close"]] = 100.0
    frame.loc[pd.Timestamp("2024-01-02"):, ["open", "high", "low", "close"]] = 60.0

    _equity, trades = evaluate_strategy(
        [holding], {"AAPL.US": frame}, "deep_drawdown_recovery",
        {
            "drawdown_threshold": 0.4, "take_profit_pct": 0.4,
            "tranches": 10, "exit_tranches": 5, "lookback_years": 3,
        },
        120_000,
    )

    assert trades == []


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
        "quality_momentum",
        "low_volatility_rotation",
        "volatility_squeeze_breakout",
    ]:
        StrategyConfig(name=name)
        signal = generate_signals([holding], {"0700.HK": df}, name, {})["0700.HK"]
        assert signal.index.equals(df.index)
        assert signal.min() >= 0
        assert signal.max() <= 0.8


def test_risk_parity_generates_portfolio_weights_without_exceeding_budget():
    holdings = [
        PaperHolding(symbol="0700", market="hk", allocation_pct=60),
        PaperHolding(symbol="9988", market="hk", allocation_pct=40),
    ]
    calm = _price_frame([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111])
    volatile = _price_frame([100, 105, 98, 108, 96, 110, 94, 112, 92, 114, 90, 116])

    StrategyConfig(name="risk_parity")
    signals = generate_signals(
        holdings,
        {"0700.HK": calm, "9988.HK": volatile},
        "risk_parity",
        {"window": 5, "rebalance": "weekly"},
    )

    assert set(signals) == {"0700.HK", "9988.HK"}
    combined = signals["0700.HK"] + signals["9988.HK"]
    assert combined.max() <= 1.0
    assert signals["0700.HK"].iloc[-1] > signals["9988.HK"].iloc[-1]


def test_price_volume_efficiency_rotation_prefers_clean_upside_with_volume_confirmation():
    holdings = [
        PaperHolding(symbol="0700", market="hk", allocation_pct=50),
        PaperHolding(symbol="9988", market="hk", allocation_pct=50),
    ]
    clean_up = _price_frame(
        [
            100, 101, 102, 103, 104, 105, 106, 107,
            108, 109, 110, 111, 112, 113, 114, 115,
        ],
        [1000, 1050, 1100, 1150, 1200, 1250, 1300, 1350,
         1400, 1450, 1500, 1550, 1600, 1650, 1700, 1750],
    )
    noisy_down = _price_frame(
        [
            100, 103, 98, 102, 97, 101, 96, 100,
            95, 99, 94, 98, 93, 97, 92, 96,
        ],
        [1000, 1300, 1700, 1200, 1900, 1300, 2100, 1400,
         2300, 1500, 2500, 1600, 2700, 1700, 2900, 1800],
    )

    StrategyConfig(name="price_volume_efficiency")
    signals = generate_signals(
        holdings,
        {"0700.HK": clean_up, "9988.HK": noisy_down},
        "price_volume_efficiency",
        {"lookback": 8, "top_n": 1, "rebalance": "weekly"},
    )

    assert set(signals) == {"0700.HK", "9988.HK"}
    assert signals["0700.HK"].iloc[-1] == 1.0
    assert signals["9988.HK"].iloc[-1] == 0.0
