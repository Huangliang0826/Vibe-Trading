"""A-share capital-flow data via Eastmoney (融资融券 / 大宗交易 / 股东户数 /
分红 / 主力资金流).

Ported from a-stock-data (Apache-2.0, © Simonlin1212) — see NOTICE. Keeps the
project's ``em_get`` anti-ban discipline: all eastmoney.com calls go through a
serialized, jittered, session-reusing gateway so a burst of requests can't get
the IP throttled.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from typing import Any

import requests

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# Eastmoney throttles at >5 req/s, ≥10 concurrent, or ≥200/min per IP. Route
# every call through em_get(): serial min-interval + jitter + Keep-Alive reuse.
_EM_SESSION = requests.Session()
_EM_SESSION.headers.update({"User-Agent": _UA})
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    _adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    _EM_SESSION.mount("https://", _adapter)
    _EM_SESSION.mount("http://", _adapter)
except Exception:  # pragma: no cover - old urllib3 lacks allowed_methods
    pass

EM_MIN_INTERVAL = 1.0  # seconds between eastmoney calls; raise for bulk jobs
_em_last_call = [0.0]


def em_get(url: str, params: dict | None = None, headers: dict | None = None,
           timeout: int = 15, **kwargs) -> requests.Response:
    """Throttled eastmoney request: min-interval + jitter + shared session.

    403 is not retried (a throttle signal — retrying makes it worse); the retry
    adapter above only covers transient 429/5xx/connection errors.
    """
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return _EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def _datacenter(report_name: str, filter_str: str, page_size: int,
                sort_columns: str, sort_types: str = "-1") -> list[dict]:
    params = {
        "reportName": report_name, "columns": "ALL",
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(_DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


def normalize_a_code(code: str) -> str | None:
    """Return a bare 6-digit A-share code, or None if it isn't one.

    Accepts ``600519`` / ``600519.SH`` / ``sh600519``.
    """
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    return digits if len(digits) == 6 else None


def margin_trading(code: str, page_size: int = 30) -> list[dict]:
    """融资融券明细(日级)。"""
    data = _datacenter("RPTA_WEB_RZRQ_GGMX", f'(SCODE="{code}")',
                       page_size, "DATE")
    return [{
        "date": str(r.get("DATE", ""))[:10],
        "rzye": r.get("RZYE", 0),      # 融资余额(元)
        "rzmre": r.get("RZMRE", 0),    # 融资买入额
        "rqye": r.get("RQYE", 0),      # 融券余额(元)
        "rzrqye": r.get("RZRQYE", 0),  # 融资融券余额合计
    } for r in data]


def holder_num_change(code: str, page_size: int = 8) -> list[dict]:
    """股东户数变化(季度级)。持续减少 = 筹码集中。"""
    data = _datacenter("RPT_HOLDERNUMLATEST", f'(SECURITY_CODE="{code}")',
                       page_size, "END_DATE")
    return [{
        "date": str(r.get("END_DATE", ""))[:10],
        "holder_num": r.get("HOLDER_NUM", 0),
        "change_ratio": r.get("HOLDER_NUM_RATIO", 0),  # 环比%
        "avg_shares": r.get("AVG_FREE_SHARES", 0),     # 户均持股
    } for r in data]


def block_trade(code: str, page_size: int = 15) -> list[dict]:
    """大宗交易记录。"""
    data = _datacenter("RPT_DATA_BLOCKTRADE", f'(SECURITY_CODE="{code}")',
                       page_size, "TRADE_DATE")
    rows = []
    for r in data:
        close = r.get("CLOSE_PRICE") or 0
        deal = r.get("DEAL_PRICE") or 0
        rows.append({
            "date": str(r.get("TRADE_DATE", ""))[:10],
            "price": deal,
            "premium_pct": round((deal / close - 1) * 100, 2) if close else 0,
            "amount": r.get("DEAL_AMT", 0),
            "buyer": r.get("BUYER_NAME", ""),
            "seller": r.get("SELLER_NAME", ""),
        })
    return rows


def dividend_history(code: str, page_size: int = 12) -> list[dict]:
    """分红送转历史。"""
    data = _datacenter("RPT_SHAREBONUS_DET", f'(SECURITY_CODE="{code}")',
                       page_size, "EX_DIVIDEND_DATE")
    return [{
        "date": str(r.get("EX_DIVIDEND_DATE", ""))[:10],
        "bonus_rmb": r.get("PRETAX_BONUS_RMB", 0),     # 每股派息(税前)
        "transfer_ratio": r.get("TRANSFER_RATIO", 0),  # 每10股转增
        "bonus_ratio": r.get("BONUS_RATIO", 0),        # 每10股送股
    } for r in data]


def stock_fund_flow_120d(code: str) -> list[dict]:
    """个股主力资金流(日级,最近120个交易日,单位元)。"""
    market_code = 1 if code.startswith("6") else 0
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": f"{market_code}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    try:
        d = em_get(url, params=params, headers=headers, timeout=15).json()
    except Exception:
        return []
    rows = []
    for line in d.get("data", {}).get("klines", []):
        p = line.split(",")
        if len(p) >= 6:
            rows.append({
                "date": p[0],
                "main_net": float(p[1]) if p[1] != "-" else 0,
                "super_net": float(p[5]) if p[5] != "-" else 0,
            })
    return rows


def _lockup_row(r: dict) -> dict:
    # RPT_LIFT_STAGE units (verified 2026-07): ABLE_FREE_SHARES in 万股,
    # FREE_RATIO a fraction of float. Normalise to raw shares + percent.
    return {
        "date": str(r.get("FREE_DATE", ""))[:10],
        "type": r.get("FREE_SHARES_TYPE", ""),
        "shares": (r.get("ABLE_FREE_SHARES") or 0) * 1e4,
        "ratio": round((r.get("FREE_RATIO") or 0) * 100, 3),
    }


def lockup_expiry(code: str, trade_date: str, forward_days: int = 90) -> dict[str, Any]:
    """限售解禁日历:历史解禁 + 未来 ``forward_days`` 天待解禁。"""
    history = [_lockup_row(r) for r in
               _datacenter("RPT_LIFT_STAGE", f'(SECURITY_CODE="{code}")', 12, "FREE_DATE")]

    end_str = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)).strftime("%Y-%m-%d")
    upcoming = [_lockup_row(r) for r in _datacenter(
        "RPT_LIFT_STAGE",
        f'(SECURITY_CODE="{code}")(FREE_DATE>=\'{trade_date}\')(FREE_DATE<=\'{end_str}\')',
        20, "FREE_DATE", "1")]

    return {"history": history, "upcoming": upcoming}


def dragon_tiger_board(code: str, trade_date: str, look_back: int = 90) -> dict[str, Any]:
    """龙虎榜:近 ``look_back`` 日上榜记录 + 最近一次买/卖席位 TOP5。"""
    start_str = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)).strftime("%Y-%m-%d")
    records = [{
        "date": str(r.get("TRADE_DATE", ""))[:10],
        "reason": r.get("EXPLANATION", ""),
        "net_buy_wan": round((r.get("BILLBOARD_NET_AMT") or 0) / 1e4, 1),  # 万元
        "turnover": round(float(r.get("TURNOVERRATE") or 0), 2),
    } for r in _datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        f'(TRADE_DATE>=\'{start_str}\')(TRADE_DATE<=\'{trade_date}\')(SECURITY_CODE="{code}")',
        50, "TRADE_DATE")]

    seats: dict[str, list] = {"buy": [], "sell": []}
    if records:
        latest = records[0]["date"]
        for side, report, sort_col in [
            ("buy", "RPT_BILLBOARD_DAILYDETAILSBUY", "BUY"),
            ("sell", "RPT_BILLBOARD_DAILYDETAILSSELL", "SELL"),
        ]:
            rows = _datacenter(
                report, f'(TRADE_DATE=\'{latest}\')(SECURITY_CODE="{code}")', 10, sort_col)
            for r in rows[:5]:
                seats[side].append({
                    "name": r.get("OPERATEDEPT_NAME", ""),
                    "buy_wan": round((r.get("BUY") or 0) / 1e4, 1),
                    "sell_wan": round((r.get("SELL") or 0) / 1e4, 1),
                    "net_wan": round((r.get("NET") or 0) / 1e4, 1),
                })
    return {"records": records, "seats": seats}


def fetch_events(code: str, trade_date: str | None = None) -> dict[str, Any]:
    """Bundle A-share event/risk data: 限售解禁 + 龙虎榜.

    Each section is independent; a failing/throttled one degrades to empty.
    """
    norm = normalize_a_code(code)
    if norm is None:
        return {"code": code, "error": "not_a_share"}
    asof = trade_date or datetime.now().strftime("%Y-%m-%d")

    try:
        lockup = lockup_expiry(norm, asof)
    except Exception:
        lockup = {"history": [], "upcoming": []}
    try:
        lhb = dragon_tiger_board(norm, asof)
    except Exception:
        lhb = {"records": [], "seats": {"buy": [], "sell": []}}

    return {"code": norm, "asof": asof, "lockup": lockup, "dragon_tiger": lhb}


def fetch_capital_flow(code: str) -> dict[str, Any]:
    """Bundle all A-share capital-flow sections for one code.

    Each section is fetched independently; a failing section becomes an empty
    list so one throttled/unavailable endpoint can't blank the whole panel.
    ``fund_flow`` is summarised to the recent-20-day main-capital net inflow
    plus the daily series.
    """
    norm = normalize_a_code(code)
    if norm is None:
        return {"code": code, "error": "not_a_share"}

    def _safe(fn):
        try:
            return fn(norm)
        except Exception:
            return []

    flow = _safe(stock_fund_flow_120d)
    recent20 = flow[-20:]
    return {
        "code": norm,
        "margin": _safe(margin_trading),
        "holders": _safe(holder_num_change),
        "block_trades": _safe(block_trade),
        "dividends": _safe(dividend_history),
        "fund_flow": flow,
        "fund_flow_20d_main_net": sum(d["main_net"] for d in recent20),
    }
