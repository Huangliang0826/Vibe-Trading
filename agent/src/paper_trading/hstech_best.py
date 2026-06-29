"""Best-strategy helper for the HSTECH forecast surface.

This reuses the paper-trading strategy generators and execution path, but keeps
the result compact so the HSTECH page can show the winning strategy's trades
directly on the forecast chart.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from backtest.engines.base import _align
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.loaders.yfinance_loader import DataLoader as YFinanceLoader
from backtest.metrics import by_symbol_stats, calc_metrics
from src.paper_trading.executor import _build_equity_curve, _build_trades_list, _run_dca
from src.paper_trading.models import PaperHolding
from src.paper_trading.storage import HKD_TO_USD
from src.paper_trading.strategies import generate_signals

HSTECH_DISPLAY_CODE = "03033"
HSTECH_PAPER_CODE = "3033"
HSTECH_PAPER_MARKET = "hk"
HSTECH_PAPER_NAME = "恒生科技指数 ETF"

STRATEGY_LABELS: dict[str, str] = {
    "buy_and_hold": "买入持有",
    "dca": "定投",
    "grid": "网格交易",
    "momentum_breakout": "动量突破",
    "moving_average_cross": "均线交叉",
    "rsi_reversion": "RSI 均值回归",
    "volatility_target": "波动率目标",
    "drawdown_rebalance": "回撤再平衡",
    "smart_dca": "智能定投",
    "trend_volatility_filter": "趋势波动过滤",
    "donchian_breakout": "唐奇安突破",
    "bollinger_reversion": "布林均值回归",
    "trailing_stop": "移动止损",
    "monthly_rebalance": "月度再平衡",
    "macd_divergence": "MACD 背离",
    "dual_momentum": "双动量轮动",
    "vol_trend_rotation": "攻守轮动",
    "atr_trend_stop": "ATR 趋势止损",
    "mean_reversion_scaleout": "均值回归分批止盈",
    "enhanced_dca_trend": "趋势增强定投",
    "breakout_pullback": "突破回踩确认",
    "quality_momentum": "收益质量动量",
    "low_volatility_rotation": "低波动防守轮动",
    "volatility_squeeze_breakout": "波动压缩突破",
    "risk_parity": "组合风险平价",
    "price_volume_efficiency": "量价效率轮动",
}

STRATEGY_PRINCIPLES: dict[str, str] = {
    "buy_and_hold": "策略原理：一次性买入并长期持有，主要赚取恒生科技 ETF 本身的长期涨幅。",
    "dca": "策略原理：把资金按固定频率分批投入，降低一次性买在高点的风险。",
    "grid": "策略原理：在历史价格区间内越跌越买、越涨越卖，主要捕捉震荡行情里的波段收益。",
    "momentum_breakout": "策略原理：价格突破近期高点时追随强势趋势，跌破趋势线或触发止损时退出。",
    "moving_average_cross": "策略原理：用短期均线和长期均线判断趋势，短线上穿长线时持有，下穿时离场。",
    "rsi_reversion": "策略原理：用 RSI 判断超买超卖，超卖时低吸，反弹到偏热区间后卖出。",
    "volatility_target": "策略原理：根据近期波动率动态调仓，波动越高仓位越低，优先控制风险暴露。",
    "drawdown_rebalance": "策略原理：价格从高点回撤越多越提高仓位，接近前高时降低仓位锁定恢复收益。",
    "smart_dca": "策略原理：在普通定投基础上根据均线偏离和波动率调整投入倍率，低估多投、过热少投。",
    "trend_volatility_filter": "策略原理：只有价格处于长期上升趋势时才持有，同时用波动率控制仓位大小。",
    "donchian_breakout": "策略原理：突破长期高点时买入，跌破近期低点时退出，属于经典趋势跟随方法。",
    "bollinger_reversion": "策略原理：价格跌破布林带下轨时认为短期偏离过大，买入等待回归均线后卖出。",
    "trailing_stop": "策略原理：趋势确认后买入，随后用移动止损线跟随价格上移，尽量保住已有利润。",
    "monthly_rebalance": "策略原理：每月恢复到目标权重，保持风险结构稳定。",
    "macd_divergence": "策略原理：当价格创新低但 MACD 抬高（底背离）且柱状图转向时买入，出现顶背离或 MACD 死叉时退出，捕捉动量反转。",
    "dual_momentum": "策略原理：每月按近期涨幅排序，只在动量为正时持有该标的，否则转为现金。",
    "vol_trend_rotation": "策略原理：趋势向上且波动低于自身长期均值时持有，否则转为现金，优先控制回撤。",
    "atr_trend_stop": "策略原理：趋势突破时买入，并用 ATR 波动幅度计算动态止损线；价格继续上涨时止损线随高点上移，趋势破坏或触发止损时离场。",
    "mean_reversion_scaleout": "策略原理：价格跌到统计下轨时认为短期超跌并买入，回到均线附近先减半，到上轨或触发止损时退出，用分批止盈降低反转失败风险。",
    "enhanced_dca_trend": "策略原理：保留定投的分批建仓纪律，但长期趋势偏弱时降低目标仓位，趋势向上且价格仍偏低时提高投入，避免在弱势里机械满仓。",
    "breakout_pullback": "策略原理：不在突破当天追高，而是先确认价格突破前高，再等待回踩突破位附近且不破短期支撑后买入，减少假突破带来的追高风险。",
    "quality_momentum": "策略原理：每月按收益质量排序，既看过去涨幅，也扣除波动率和最大回撤惩罚，只持有表现强且回撤质量更好的标的。",
    "low_volatility_rotation": "策略原理：每月在趋势未破的标的里选择近期波动最低者，目标不是追求最强涨幅，而是优先降低组合波动和下行风险。",
    "volatility_squeeze_breakout": "策略原理：先等待布林带宽度/波动率降到历史低分位，随后只有价格向上突破且成交量确认时买入，捕捉压缩后的趋势释放。",
    "risk_parity": "策略原理：按近期波动率反向分配组合权重，波动大的标的少配，波动小的标的多配，让组合风险贡献更均衡。",
    "price_volume_efficiency": "策略原理：把价格行为切成上涨效率和下跌效率，再看成交量是否配合；上涨高效且放量确认加分，下跌高效且放量确认扣分，最后按综合 rank 轮动持有前几名。",
}

STRATEGY_NAMES: tuple[str, ...] = tuple(STRATEGY_LABELS)


def default_start_date() -> str:
    return "2020-01-01"


def default_end_date() -> str:
    return date.today().isoformat()


def normalize_best_strategy_symbol(code: str, market: str) -> tuple[str, str, str]:
    """Return (paper_symbol, yahoo_symbol, display_code) for a single-symbol run."""
    mk = market.lower().strip()
    symbol = code.strip().upper()
    if mk == "hk":
        digits = "".join(ch for ch in symbol.replace(".HK", "") if ch.isdigit())
        if not digits:
            raise ValueError(f"Invalid HK symbol: {code}")
        n = int(digits)
        return f"{n:04d}", f"{n:04d}.HK", f"{n:04d}"
    if mk == "us":
        bare = symbol.replace(".US", "")
        if not bare:
            raise ValueError(f"Invalid US symbol: {code}")
        return bare, f"{bare}.US", bare
    raise ValueError("market must be 'hk' or 'us'")


def run_hstech_best_strategy(
    start_date: str | None = None,
    end_date: str | None = None,
    initial_usd: float = 100_000.0,
    initial_hkd: float = 1_000_000.0,
) -> dict[str, Any]:
    """Run the paper-trading strategy pool for 3033.HK and display it as 03033.HK."""
    return run_single_symbol_best_strategy(
        code=HSTECH_PAPER_CODE,
        market=HSTECH_PAPER_MARKET,
        name=HSTECH_PAPER_NAME,
        display_code=HSTECH_DISPLAY_CODE,
        start_date=start_date,
        end_date=end_date,
        initial_usd=initial_usd,
        initial_hkd=initial_hkd,
        run_prefix="hstech",
        title_prefix="HSTECH",
    )


def run_single_symbol_best_strategy(
    code: str,
    market: str,
    name: str | None = None,
    display_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    initial_usd: float = 100_000.0,
    initial_hkd: float = 1_000_000.0,
    run_prefix: str | None = None,
    title_prefix: str | None = None,
) -> dict[str, Any]:
    """Run the paper-trading strategy pool for one HK/US symbol and return the winner."""
    start = start_date or default_start_date()
    end = end_date or default_end_date()
    mk = market.lower().strip()
    paper_symbol, yahoo_symbol, normalized_display = normalize_best_strategy_symbol(code, mk)
    shown_code = display_code or normalized_display
    shown_name = name or shown_code
    prefix = run_prefix or f"{mk}-{normalized_display.lower()}"
    title = title_prefix or shown_code

    holding = PaperHolding(symbol=paper_symbol, market=mk, allocation_pct=100.0)
    initial_total_usd = round(initial_usd + initial_hkd * HKD_TO_USD, 2)
    loader = YFinanceLoader()
    data_map = loader.fetch([yahoo_symbol], start, end, interval="1D")
    if not data_map:
        raise ValueError(f"No price data fetched for {yahoo_symbol}")

    runs = [
        _run_strategy(
            strategy_name=name,
            holding=holding,
            data_map=data_map,
            start_date=start,
            end_date=end,
            initial_total_usd=initial_total_usd,
            run_prefix=prefix,
            title_prefix=title,
        )
        for name in STRATEGY_NAMES
    ]
    completed = [run for run in runs if run["status"] == "completed" and run.get("metrics")]
    if not completed:
        failed = next((run for run in runs if run["status"] == "failed"), None)
        raise ValueError((failed or {}).get("error") or f"All paper strategies failed for {shown_code}")

    best = sorted(completed, key=_strategy_sort_key)[0]
    summary = summarize_best_strategy(runs, best["strategy"]["name"], display_code=shown_code)
    return {
        "code": shown_code,
        "name": shown_name,
        "market": mk,
        "start_date": start,
        "end_date": end,
        "initial_total_usd": initial_total_usd,
        "best": best,
        "candidates": [_candidate_row(run) for run in runs],
        "summary": summary,
    }


def strategy_params(strategy_name: str) -> dict[str, Any]:
    if strategy_name in {"dca", "smart_dca", "enhanced_dca_trend"}:
        return {"frequency": "monthly"}
    if strategy_name == "grid":
        return {"grid_count": 5}
    return {}


_strategy_params = strategy_params


def _run_strategy(
    strategy_name: str,
    holding: PaperHolding,
    data_map: dict[str, pd.DataFrame],
    start_date: str,
    end_date: str,
    initial_total_usd: float,
    run_prefix: str = "hstech",
    title_prefix: str = "HSTECH",
) -> dict[str, Any]:
    params = strategy_params(strategy_name)
    try:
        if strategy_name in {"dca", "smart_dca"}:
            equity_series, trade_records = _run_dca(
                initial_total_usd,
                [holding],
                data_map,
                params,
                smart=strategy_name == "smart_dca",
            )
        else:
            signal_map = generate_signals([holding], data_map, strategy_name, params)
            valid_codes = sorted(c for c in signal_map if c in data_map)
            if not valid_codes:
                raise ValueError("No valid signals generated")
            dates, close_df, target_pos, _ret_df = _align(data_map, signal_map, valid_codes)
            engine = GlobalEquityEngine({"initial_cash": initial_total_usd}, market=holding.market)
            engine._execute_bars(dates, data_map, close_df, target_pos, valid_codes)
            equity_series = pd.Series(
                [s.equity for s in engine.equity_snapshots],
                index=[s.timestamp for s in engine.equity_snapshots],
            )
            trade_records = engine.trades

        metrics = calc_metrics(equity_series, trade_records, initial_total_usd, bars_per_year=None)
        metrics["by_symbol"] = by_symbol_stats(trade_records)
        trades = _build_trades_list(trade_records)
        return {
            "run_id": f"{run_prefix}-{strategy_name}",
            "title": f"{title_prefix} 最优策略候选 - {STRATEGY_LABELS[strategy_name]}",
            "status": "completed",
            "strategy": {"name": strategy_name, "label": STRATEGY_LABELS[strategy_name], "params": params},
            "start_date": start_date,
            "end_date": end_date,
            "metrics": metrics,
            "equity_curve": _build_equity_curve(equity_series),
            "trades": _paired_trade_signals(trades),
            "paper_trades": trades,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - keep one failed strategy from hiding the rest.
        return {
            "run_id": f"{run_prefix}-{strategy_name}",
            "title": f"{title_prefix} 最优策略候选 - {STRATEGY_LABELS[strategy_name]}",
            "status": "failed",
            "strategy": {"name": strategy_name, "label": STRATEGY_LABELS[strategy_name], "params": params},
            "start_date": start_date,
            "end_date": end_date,
            "metrics": None,
            "equity_curve": [],
            "trades": [],
            "paper_trades": [],
            "error": str(exc),
        }


def _paired_trade_signals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    if rows and "entry_time" in rows[0]:
        for trade in rows:
            signals.append({
                "entry_date": str(trade.get("entry_time")),
                "exit_date": str(trade.get("exit_time")),
                "entry_price": float(trade.get("entry_price") or 0),
                "exit_price": float(trade.get("exit_price") or trade.get("entry_price") or 0),
                "pnl_pct": float(trade.get("pnl_pct") or 0),
                "holding_bars": int(trade.get("holding_bars") or 0),
                "exit_reason": str(trade.get("exit_reason") or "signal"),
            })
        return signals

    for i in range(0, len(rows), 2):
        entry = rows[i]
        exit_row = rows[i + 1] if i + 1 < len(rows) else entry
        signals.append({
            "entry_date": str(entry.get("timestamp")),
            "exit_date": str(exit_row.get("timestamp")),
            "entry_price": float(entry.get("price") or 0),
            "exit_price": float(exit_row.get("price") or entry.get("price") or 0),
            "pnl_pct": float(exit_row.get("return_pct") or 0),
            "holding_bars": int(exit_row.get("holding_days") or 0),
            "exit_reason": str(exit_row.get("reason") or "signal"),
        })
    return signals


def _strategy_sort_key(run: dict[str, Any]) -> tuple[float, float, float]:
    metrics = run.get("metrics") or {}
    sharpe = _finite(metrics.get("sharpe"), -1e18)
    total_return = _finite(metrics.get("total_return"), -1e18)
    max_drawdown = _finite(metrics.get("max_drawdown"), -1e18)
    return (-sharpe, -total_return, -max_drawdown)


def _candidate_row(run: dict[str, Any]) -> dict[str, Any]:
    metrics = run.get("metrics") or {}
    return {
        "strategy": run["strategy"],
        "status": run["status"],
        "metrics": {
            "total_return": metrics.get("total_return"),
            "sharpe": metrics.get("sharpe"),
            "max_drawdown": metrics.get("max_drawdown"),
            "trade_count": metrics.get("trade_count"),
        } if metrics else None,
        "error": run.get("error"),
    }


def summarize_best_strategy(
    runs: list[dict[str, Any]],
    best_strategy_name: str,
    display_code: str = HSTECH_DISPLAY_CODE,
) -> str:
    completed = [run for run in runs if run.get("status") == "completed" and run.get("metrics")]
    best = next((run for run in completed if run["strategy"]["name"] == best_strategy_name), None)
    if best is None:
        return ""

    sorted_runs = sorted(completed, key=_strategy_sort_key)
    second = next((run for run in sorted_runs if run["strategy"]["name"] != best_strategy_name), None)
    metrics = best["metrics"]
    best_name = STRATEGY_LABELS.get(best_strategy_name, best_strategy_name)
    best_sharpe = _finite(metrics.get("sharpe"))
    best_return = _finite(metrics.get("total_return"))
    best_drawdown = _finite(metrics.get("max_drawdown"))
    trade_count = int(_finite(metrics.get("trade_count"), len(best.get("trades") or [])))

    parts = [
        STRATEGY_PRINCIPLES.get(best_strategy_name, f"策略原理：{best_name} 根据历史价格信号动态调整仓位。"),
        f"{best_name} 在 {display_code} 当前回测区间里综合排名第一，夏普比率为 {best_sharpe:.2f}，总收益为 {_fmt_pct(best_return)}，最大亏损为 {_fmt_pct(best_drawdown)}。",
    ]
    if second and second.get("metrics"):
        second_metrics = second["metrics"]
        second_name = STRATEGY_LABELS.get(second["strategy"]["name"], second["strategy"]["name"])
        parts.append(
            f"相比第二名 {second_name}，它的夏普高出 {best_sharpe - _finite(second_metrics.get('sharpe')):.2f}，"
            f"总收益差距为 {_fmt_pct(best_return - _finite(second_metrics.get('total_return')))}。"
        )
    risk_note = "回撤仍然偏高，适合作为候选信号而不是机械实盘指令。" if best_drawdown < -0.2 else "回撤相对可控，没有单纯靠承受更大亏损取胜。"
    parts.append(f"本次交易次数为 {trade_count} 次；{risk_note}")
    parts.append(_latest_trade_summary(best.get("trades") or [], display_code))
    return " ".join(parts)


def _latest_trade_summary(trades: list[dict[str, Any]], display_code: str = HSTECH_DISPLAY_CODE) -> str:
    if not trades:
        return "最新交易：暂无交易记录，当前没有可跟随的买卖动作。"
    actionable = [trade for trade in trades if trade.get("exit_reason") != "end_of_backtest"]
    latest = sorted(actionable or trades, key=lambda tr: str(tr.get("exit_date")), reverse=True)[0]
    if latest.get("exit_reason") == "end_of_backtest":
        return (
            f"最新交易：最近一次买入是 {latest.get('entry_date')}，价格 {float(latest.get('entry_price') or 0):.2f}；"
            "之后没有新的主动卖出信号，当前更接近继续持有或等待下一次信号。"
        )
    return (
        f"最新交易：{latest.get('exit_date')} 卖出 {display_code}，价格 {float(latest.get('exit_price') or 0):.2f}；"
        "等待下一次买入信号。"
    )


def _finite(value: Any, fallback: float = 0.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return fallback
    return x if pd.notna(x) else fallback


def _fmt_pct(value: float) -> str:
    return f"{value * 100:+.1f}%"
