from src.paper_trading.hstech_best import _candidate_row, _paired_trade_signals, summarize_best_strategy


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

    summary = summarize_best_strategy(runs, "donchian_breakout")

    assert summary.startswith("策略原理：突破长期高点时买入")
    assert "唐奇安突破" in summary
    assert "最新交易：2024-03-04 卖出 03033.HK" in summary


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
