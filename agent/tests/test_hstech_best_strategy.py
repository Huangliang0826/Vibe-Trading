import pandas as pd

from src.paper_trading.hstech_best import (
    _candidate_row,
    _paired_trade_signals,
    normalize_best_strategy_symbol,
    strategy_params,
    summarize_best_strategy,
    select_single_symbol_robust_strategy,
    run_selected_single_symbol_strategy,
    _robust_validation_profile,
)


def test_paired_trade_signals_convert_paper_trade_rows():
    rows = [
        {
            "timestamp": "2024-01-02",
            "side": "buy",
            "price": 10.0,
            "qty": 100,
            "reason": "signal",
            "pnl": 0.0,
            "holding_days": 0,
            "return_pct": 0.0,
        },
        {
            "timestamp": "2024-02-03",
            "side": "sell",
            "price": 12.0,
            "qty": 100,
            "reason": "signal",
            "pnl": 200.0,
            "holding_days": 32,
            "return_pct": 20.0,
        },
    ]

    assert _paired_trade_signals(rows) == [
        {
            "entry_date": "2024-01-02",
            "exit_date": "2024-02-03",
            "entry_price": 10.0,
            "exit_price": 12.0,
            "pnl_pct": 20.0,
            "holding_bars": 32,
            "exit_reason": "signal",
        }
    ]


def test_paired_trade_signals_convert_trade_record_rows():
    rows = [
        {
            "symbol": "3033.HK",
            "direction": 1,
            "entry_price": 8.1682,
            "exit_price": 7.8871,
            "entry_time": "2020-11-06",
            "exit_time": "2020-12-29",
            "size": 27900,
            "pnl": -7841.43,
            "pnl_pct": -3.4409,
            "exit_reason": "signal",
            "holding_bars": 36,
            "commission": 549.4007,
        }
    ]

    assert _paired_trade_signals(rows) == [
        {
            "entry_date": "2020-11-06",
            "exit_date": "2020-12-29",
            "entry_price": 8.1682,
            "exit_price": 7.8871,
            "pnl_pct": -3.4409,
            "holding_bars": 36,
            "exit_reason": "signal",
        }
    ]


def test_normalize_best_strategy_symbol_handles_hk_and_us():
    assert normalize_best_strategy_symbol("00700", "hk") == ("0700", "0700.HK", "0700")
    assert normalize_best_strategy_symbol("0700.HK", "hk") == ("0700", "0700.HK", "0700")
    assert normalize_best_strategy_symbol("AAPL", "us") == ("AAPL", "AAPL.US", "AAPL")
    assert normalize_best_strategy_symbol("AAPL.US", "us") == ("AAPL", "AAPL.US", "AAPL")


def test_summary_starts_with_strategy_principle_and_latest_trade():
    runs = [
        {
            "status": "completed",
            "strategy": {"name": "buy_and_hold"},
            "metrics": {"sharpe": 0.4, "total_return": 0.1, "max_drawdown": -0.2, "trade_count": 1},
            "trades": [],
        },
        {
            "status": "completed",
            "strategy": {"name": "donchian_breakout"},
            "metrics": {"sharpe": 1.2, "total_return": 0.3, "max_drawdown": -0.12, "trade_count": 2},
            "trades": [
                {
                    "entry_date": "2024-01-02",
                    "exit_date": "2024-03-04",
                    "entry_price": 10.0,
                    "exit_price": 12.0,
                    "pnl_pct": 20.0,
                    "holding_bars": 44,
                    "exit_reason": "signal",
                }
            ],
        },
    ]

    summary = summarize_best_strategy(runs, "donchian_breakout", display_code="0700")

    assert summary.startswith("策略原理：突破长期高点时买入")
    assert "唐奇安突破" in summary
    assert "最新交易：2024-03-04 卖出 0700" in summary


def test_candidate_row_keeps_compact_metrics():
    row = _candidate_row({
        "status": "completed",
        "strategy": {"name": "grid", "label": "网格交易", "params": {"grid_count": 5}},
        "metrics": {
            "total_return": 0.2,
            "sharpe": 0.8,
            "max_drawdown": -0.1,
            "trade_count": 4,
            "annual_return": 0.12,
        },
        "error": None,
    })

    assert row == {
        "strategy": {"name": "grid", "label": "网格交易", "params": {"grid_count": 5}},
        "status": "completed",
        "metrics": {
            "total_return": 0.2,
            "sharpe": 0.8,
            "max_drawdown": -0.1,
            "trade_count": 4,
        },
        "error": None,
    }


def test_strategy_params_exposes_catalog_defaults():
    assert strategy_params("dca") == {"frequency": "monthly"}
    assert strategy_params("grid") == {"grid_count": 5}
    assert strategy_params("buy_and_hold") == {}


class _FakeLoader:
    def __init__(self):
        self.calls = []

    def fetch(self, codes, start, end, interval="1D"):
        self.calls.append((codes, start, end, interval))
        index = pd.bdate_range("2008-01-02", "2026-07-01")
        return {codes[0]: pd.DataFrame({"close": range(1, len(index) + 1)}, index=index)}


def test_robust_selection_reserves_latest_year_and_uses_first_oos_pass(monkeypatch):
    loader = _FakeLoader()
    robust_calls = []

    def robust_runner(holdings, start_date, end_date, initial_cash, specs, window_years, step_years):
        robust_calls.append((start_date, end_date, [spec["name"] for spec in specs]))
        return {
            "best_strategy": "buy_and_hold",
            "strategies": [
                {"name": "buy_and_hold", "mean_rank": 1, "worst_rank": 2, "rank_std": 0.5, "ok_count": 7, "mean_score": 1},
                {"name": "donchian_breakout", "mean_rank": 2, "worst_rank": 3, "rank_std": 0.6, "ok_count": 7, "mean_score": 0.8},
            ],
            "windows": [], "data_start": "2008-01-02", "data_end": "2025-07-01", "window_years": 3,
        }

    def strategy_runner(strategy_name, **kwargs):
        passed = strategy_name == "donchian_breakout"
        return {
            "status": "completed", "strategy": {"name": strategy_name},
            "metrics": {"sharpe": 0.8 if passed else -0.2, "total_return": 0.1, "max_drawdown": -0.1},
            "trades": [],
        }

    selection = select_single_symbol_robust_strategy(
        "NVDA", "us", end_date="2026-07-02", loader=loader,
        robust_runner=robust_runner, strategy_runner=strategy_runner,
    )

    assert robust_calls[0][1] == "2025-07-01"
    assert selection["selected_strategy"] == "donchian_breakout"
    assert selection["reliable"] is True
    assert selection["oos_validation"]["start_date"] == "2025-07-02"
    assert selection["oos_validation"]["passed"] is True


def test_daily_selected_strategy_evaluates_only_cached_strategy():
    loader = _FakeLoader()
    seen = []

    def strategy_runner(strategy_name, **kwargs):
        seen.append(strategy_name)
        return {
            "status": "completed", "strategy": {"name": strategy_name, "label": "唐奇安突破"},
            "metrics": {"sharpe": 1.0, "total_return": 0.2, "max_drawdown": -0.1},
            "trades": [],
        }

    result = run_selected_single_symbol_strategy(
        "NVDA", "us", "NVIDIA", "NVDA",
        selection={
            "selected_strategy": "donchian_breakout", "reliable": True,
            "oos_validation": {"passed": True}, "robust_result": {"strategies": []},
        },
        end_date="2026-07-02", loader=loader, strategy_runner=strategy_runner,
    )

    assert seen == ["donchian_breakout"]
    assert result["best"]["strategy"]["name"] == "donchian_breakout"
    assert result["reliable"] is True
    assert result["signal_as_of"] == "2026-07-02"


def test_short_history_uses_low_confidence_six_month_validation_profile():
    profile = _robust_validation_profile(620)

    assert profile == {
        "window_years": 1,
        "step_years": 1,
        "holdout_months": 6,
        "confidence_level": "low",
        "history_note": "历史不足4年，使用1年滚动窗口和6个月样本外验证",
    }


def test_less_than_two_years_is_not_enough_for_robust_selection():
    try:
        _robust_validation_profile(400)
    except ValueError as exc:
        assert "two years" in str(exc)
    else:
        raise AssertionError("expected short history to be rejected")
