"""event: earnings proximity, insider buying, analyst upgrades via yfinance."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import pandas as pd
import yfinance as yf

from src.scanner.core import Candidate
from src.scanner.providers.base import SignalProvider

log = logging.getLogger(__name__)

_INSIDER_LOOKBACK_DAYS = 30
_UPGRADE_LOOKBACK_DAYS = 30
_EARNINGS_HORIZON_DAYS = 14


def _earnings_proximity(ticker: yf.Ticker, asof: dt.date) -> float | None:
    """Days until next earnings. Returns None if unavailable."""
    try:
        cal = ticker.calendar
        if not cal or "Earnings Date" not in cal:
            return None
        dates = cal["Earnings Date"]
        if not isinstance(dates, list):
            dates = [dates]
        future = [d for d in dates if d >= asof]
        if not future:
            return None
        return (min(future) - asof).days
    except Exception:
        return None


def _insider_net_buys(ticker: yf.Ticker, asof: dt.date) -> dict[str, float] | None:
    """Net insider buy count and value in the last 30 days."""
    try:
        txns = ticker.insider_transactions
        if txns is None or txns.empty:
            return None
        if "Start Date" not in txns.columns:
            return None
        cutoff = asof - dt.timedelta(days=_INSIDER_LOOKBACK_DAYS)
        txns = txns.copy()
        txns["_date"] = pd.to_datetime(txns["Start Date"]).dt.date
        recent = txns[(txns["_date"] >= cutoff) & (txns["_date"] <= asof)]
        if recent.empty:
            return None
        txn_col = "Transaction" if "Transaction" in recent.columns else None
        if txn_col is None:
            return None
        text_col = recent[txn_col].str.lower().fillna("")
        buys = recent[text_col.str.contains("purchase", na=False)]
        sells = recent[text_col.str.contains("sale", na=False)]
        buy_count = len(buys)
        sell_count = len(sells)
        buy_value = float(buys["Value"].fillna(0).sum()) if "Value" in buys.columns else 0
        sell_value = float(sells["Value"].fillna(0).sum()) if "Value" in sells.columns else 0
        return {
            "net_count": buy_count - sell_count,
            "net_value": buy_value - sell_value,
            "buy_count": buy_count,
            "sell_count": sell_count,
        }
    except Exception:
        return None


def _analyst_upgrades(ticker: yf.Ticker, asof: dt.date) -> dict[str, int] | None:
    """Count upgrades vs downgrades in the last 30 days."""
    try:
        ud = ticker.upgrades_downgrades
        if ud is None or ud.empty:
            return None
        cutoff = asof - dt.timedelta(days=_UPGRADE_LOOKBACK_DAYS)
        if ud.index.name == "GradeDate" or "GradeDate" in str(ud.index.dtype):
            ud = ud.copy()
            ud["_date"] = pd.to_datetime(ud.index).date
        elif "GradeDate" in ud.columns:
            ud = ud.copy()
            ud["_date"] = pd.to_datetime(ud["GradeDate"]).dt.date
        else:
            return None
        recent = ud[(ud["_date"] >= cutoff) & (ud["_date"] <= asof)]
        if recent.empty:
            return None
        action = recent["Action"].str.lower().fillna("") if "Action" in recent.columns else pd.Series()
        upgrades = int((action == "upgrade").sum() + (action == "up").sum())
        downgrades = int((action == "downgrade").sum() + (action == "down").sum())
        initiations = int((action == "init").sum() + (action.str.contains("init", na=False)).sum())
        maintains = int(len(recent) - upgrades - downgrades - initiations)
        return {
            "upgrades": upgrades,
            "downgrades": downgrades,
            "initiations": initiations,
            "total": len(recent),
        }
    except Exception:
        return None


SIGNAL_LABELS: dict[str, str] = {
    "earnings_proximity": "财报临近",
    "insider_buying": "内部人买入",
    "analyst_upgrade": "分析师调升",
}

_WEIGHTS: dict[str, float] = {
    "earnings_proximity": 35.0,
    "insider_buying": 35.0,
    "analyst_upgrade": 30.0,
}


def _score_earnings(days_until: float) -> float:
    """0-100: closer earnings = higher score. 0 days = 100, 14 days = 0."""
    if days_until < 0 or days_until > _EARNINGS_HORIZON_DAYS:
        return 0.0
    return max(0.0, (1.0 - days_until / _EARNINGS_HORIZON_DAYS)) * 100.0


def _score_insider(info: dict[str, float]) -> float:
    """0-100 based on net buy count and value."""
    net_count = info.get("net_count", 0)
    if net_count <= 0:
        return 0.0
    count_score = min(net_count / 5.0, 1.0) * 50.0
    net_value = info.get("net_value", 0)
    value_score = min(max(net_value, 0) / 5_000_000, 1.0) * 50.0
    return count_score + value_score


def _score_analyst(info: dict[str, int]) -> float:
    """0-100 based on upgrade/downgrade ratio."""
    upgrades = info.get("upgrades", 0)
    downgrades = info.get("downgrades", 0)
    total = info.get("total", 0)
    if total == 0:
        return 0.0
    net = upgrades - downgrades
    if net <= 0:
        return 0.0
    ratio_score = min(net / 3.0, 1.0) * 60.0
    coverage_score = min(total / 10.0, 1.0) * 40.0
    return ratio_score + coverage_score


def _strip_suffix(sym: str) -> str:
    return sym.rsplit(".", 1)[0] if sym.endswith(".US") else sym


class EventProvider(SignalProvider):
    """Detect event catalysts: earnings proximity, insider buying, analyst upgrades."""

    provider_id = "event"

    def __init__(self, top_n: int = 20, min_score: float = 10.0):
        self._top_n = top_n
        self._min_score = min_score

    def compute(self, panel: dict[str, pd.DataFrame], asof: str) -> list[Candidate]:
        close = panel.get("close")
        if close is None or close.empty:
            return []

        asof_date = dt.date.fromisoformat(asof)
        symbols = [c for c in close.columns if not str(c).startswith("_")]

        batch_size = 10
        results: list[Candidate] = []

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            tickers = {sym: yf.Ticker(_strip_suffix(str(sym))) for sym in batch}

            for sym, ticker in tickers.items():
                signals: dict[str, float] = {}
                detail: dict[str, float] = {}

                earnings_days = _earnings_proximity(ticker, asof_date)
                if earnings_days is not None and earnings_days <= _EARNINGS_HORIZON_DAYS:
                    score = _score_earnings(earnings_days)
                    signals["earnings_proximity"] = score
                    detail[SIGNAL_LABELS["earnings_proximity"]] = round(score, 1)

                insider = _insider_net_buys(ticker, asof_date)
                if insider is not None:
                    score = _score_insider(insider)
                    if score > 0:
                        signals["insider_buying"] = score
                        detail[SIGNAL_LABELS["insider_buying"]] = round(score, 1)

                analyst = _analyst_upgrades(ticker, asof_date)
                if analyst is not None:
                    score = _score_analyst(analyst)
                    if score > 0:
                        signals["analyst_upgrade"] = score
                        detail[SIGNAL_LABELS["analyst_upgrade"]] = round(score, 1)

                if not signals:
                    continue

                weighted_sum = 0.0
                total_weight = 0.0
                for name, scored in signals.items():
                    w = _WEIGHTS.get(name, 10.0)
                    weighted_sum += scored * w
                    total_weight += w

                if total_weight == 0:
                    continue

                composite = weighted_sum / total_weight
                if composite < self._min_score:
                    continue

                detail = dict(sorted(detail.items(), key=lambda kv: -kv[1]))
                top_names = [k for k, v in list(detail.items())[:2] if v > 0]
                attribution = (
                    "、".join(top_names) + " 催化" if top_names else "事件催化"
                )

                results.append(Candidate(
                    symbol=str(sym),
                    score=round(composite, 2),
                    provider_id=self.provider_id,
                    attribution=attribution,
                    detail=detail,
                ))

        results.sort(key=lambda c: -c.score)
        return results[: self._top_n]
