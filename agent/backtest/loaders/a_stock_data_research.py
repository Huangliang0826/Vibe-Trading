"""a-stock-data research helpers: 研报 / 新闻 / 基础数据 / 公告 (+ realtime 行情).

The backtest loader contract only covers OHLCV, so the non-OHLCV layers of
simonlin1212/a-stock-data (SKILL.md V3.2.2) live here as plain, agent-callable
functions. One clean entry point per category:

    fetch_reports(code)        — 研报：东财研报列表 + 同花顺一致预期 EPS
    fetch_news(code=None)      — 新闻：东财个股新闻 / 全球 7x24 资讯
    fetch_stock_info(code)     — 基础数据：东财个股基本面快照
    fetch_financials(code)     — 基础数据：新浪财报三表
    fetch_announcements(code)  — 公告：巨潮全文检索
    fetch_quote(codes)         — 行情(实时估值)：腾讯 PE/PB/市值/换手率

All East Money calls go through the shared, process-global ``em_get`` limiter in
:mod:`backtest.loaders._a_stock_data_common` so they share one anti-ban budget
with the OHLCV loader. Every function accepts any A-share symbol form
(``688017`` / ``SH688017`` / ``688017.SH``) and normalizes internally.

These hit mainland-China servers (东财/同花顺/新浪/巨潮/腾讯/百度); from a blocked
network they return empty lists / dicts rather than raising.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from io import StringIO
from typing import Optional

import pandas as pd
import requests

from backtest.loaders._a_stock_data_common import UA, em_get, normalize_ticker

logger = logging.getLogger(__name__)

_REPORT_API = "https://reportapi.eastmoney.com/report/list"
_STOCK_NEWS_URL = "https://search-api-web.eastmoney.com/search/jsonp"
_GLOBAL_NEWS_URL = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
_STOCK_INFO_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_SINA_FIN_URL = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
_CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
_CNINFO_ORGID_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
_TENCENT_URL = "https://qt.gtimg.cn/q="


# ---------------------------------------------------------------------------
# 研报 (research reports)
# ---------------------------------------------------------------------------


def eastmoney_reports(code: str, max_pages: int = 5) -> list[dict]:
    """东财研报列表。Key fields: title / publishDate / orgSName / emRatingName /
    infoCode / predictThisYearEps / predictNextYearEps / predictNextTwoYearEps."""
    code = normalize_ticker(code)
    all_records: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        try:
            r = em_get(_REPORT_API, params=params,
                       headers={"Referer": "https://data.eastmoney.com/"}, timeout=30)
            d = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("a_stock_data reports failed for %s p%d: %s", code, page, exc)
            break
        rows = d.get("data") or []
        if not rows:
            break
        all_records.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
    return all_records


def ths_eps_forecast(code: str) -> pd.DataFrame:
    """同花顺机构一致预期 EPS（解析 basic.10jqka.com.cn HTML 表格）。
    返回 DataFrame：年度 / 预测机构数 / 最小值 / 均值(一致预期) / 最大值。"""
    code = normalize_ticker(code)
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    headers = {"User-Agent": UA, "Referer": "https://basic.10jqka.com.cn/"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "gbk"
        dfs = pd.read_html(StringIO(r.text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("a_stock_data ths_eps_forecast failed for %s: %s", code, exc)
        return pd.DataFrame()
    for df in dfs:
        cols = [str(c) for c in df.columns]
        if any("每股收益" in c or "均值" in c for c in cols):
            return df
    return dfs[0] if dfs else pd.DataFrame()


def fetch_reports(code: str, max_pages: int = 5, with_eps_forecast: bool = True) -> dict:
    """研报聚合入口：东财研报列表 + （可选）同花顺一致预期 EPS。

    Returns ``{"reports": [...], "eps_forecast": [...]}`` (eps_forecast empty
    when disabled or unavailable)."""
    reports = eastmoney_reports(code, max_pages=max_pages)
    eps_forecast: list[dict] = []
    if with_eps_forecast:
        df = ths_eps_forecast(code)
        if not df.empty:
            eps_forecast = df.to_dict(orient="records")
    return {"reports": reports, "eps_forecast": eps_forecast}


# ---------------------------------------------------------------------------
# 新闻 (news)
# ---------------------------------------------------------------------------


def eastmoney_stock_news(code: str, page_size: int = 20) -> list[dict]:
    """东财个股新闻（JSONP）。返回 [{title, content, time, source, url}]."""
    code = normalize_ticker(code)
    inner = json.dumps({
        "uid": "", "keyword": code, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                  "pageIndex": 1, "pageSize": page_size, "preTag": "", "postTag": ""}},
    }, separators=(",", ":"))
    params = {"cb": "jQuery_news", "param": inner}
    headers = {"User-Agent": UA, "Referer": "https://so.eastmoney.com/"}
    try:
        r = em_get(_STOCK_NEWS_URL, params=params, headers=headers, timeout=15)
        text = r.text
        d = json.loads(text[text.index("(") + 1: text.rindex(")")])
    except Exception as exc:  # noqa: BLE001
        logger.warning("a_stock_data stock_news failed for %s: %s", code, exc)
        return []
    rows = []
    for a in d.get("result", {}).get("cmsArticleWebOld", []) or []:
        rows.append({
            "title": re.sub(r"<[^>]+>", "", a.get("title", "")),
            "content": re.sub(r"<[^>]+>", "", a.get("content", ""))[:200],
            "time": a.get("date", ""),
            "source": a.get("mediaName", ""),
            "url": a.get("url", ""),
        })
    return rows


def eastmoney_global_news(page_size: int = 50) -> list[dict]:
    """东财全球财经资讯（7x24 滚动）。返回 [{title, summary, time}]."""
    params = {
        "client": "web", "biz": "web_724", "fastColumn": "102", "sortEnd": "",
        "pageSize": str(page_size), "req_trace": str(uuid.uuid4()),
    }
    headers = {"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"}
    try:
        r = em_get(_GLOBAL_NEWS_URL, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("a_stock_data global_news failed: %s", exc)
        return []
    return [
        {"title": i.get("title", ""), "summary": i.get("summary", "")[:200], "time": i.get("showTime", "")}
        for i in d.get("data", {}).get("fastNewsList", []) or []
    ]


def fetch_news(code: Optional[str] = None, page_size: int = 20) -> list[dict]:
    """新闻入口：传 ``code`` 取个股新闻，否则取全球 7x24 资讯。"""
    if code:
        return eastmoney_stock_news(code, page_size=page_size)
    return eastmoney_global_news(page_size=page_size)


# ---------------------------------------------------------------------------
# 基础数据 (fundamentals)
# ---------------------------------------------------------------------------


def fetch_stock_info(code: str) -> dict:
    """东财个股基本面快照：name / industry / 总股本 / 流通股 / 总市值 / 流通市值 / 上市日期。"""
    code = normalize_ticker(code)
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
        "secid": f"{market_code}.{code}",
    }
    try:
        r = em_get(_STOCK_INFO_URL, params=params, headers={"User-Agent": UA}, timeout=10)
        d = r.json().get("data", {}) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("a_stock_data stock_info failed for %s: %s", code, exc)
        return {}
    return {
        "code": d.get("f57", ""),
        "name": d.get("f58", ""),
        "industry": d.get("f127", ""),
        "total_shares": d.get("f84", 0),
        "float_shares": d.get("f85", 0),
        "mcap": d.get("f116", 0),
        "float_mcap": d.get("f117", 0),
        "list_date": str(d.get("f189", "")),
        "price": d.get("f43", 0),
    }


def fetch_financials(code: str, report_type: str = "lrb", num: int = 8) -> list[dict]:
    """新浪财报三表。``report_type``: ``fzb``(资产负债)/``lrb``(利润)/``llb``(现金流量)。
    返回按报告期倒序的记录列表。"""
    code = normalize_ticker(code)
    prefix = "sh" if code.startswith("6") else "sz"
    params = {"paperCode": f"{prefix}{code}", "source": report_type,
              "type": "0", "page": "1", "num": str(num)}
    try:
        r = requests.get(_SINA_FIN_URL, params=params, headers={"User-Agent": UA}, timeout=15)
        report_list = r.json().get("result", {}).get("data", {}).get("report_list", {}) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("a_stock_data financials failed for %s: %s", code, exc)
        return []
    rows = []
    for period in sorted(report_list.keys(), reverse=True)[:num]:
        obj = report_list[period]
        rec = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
        for it in obj.get("data", []) or []:
            title = it.get("item_title", "")
            if not title or it.get("item_value") is None:
                continue
            rec[title] = it.get("item_value")
            tongbi = it.get("item_tongbi")
            if tongbi not in (None, ""):
                rec[title + "_同比"] = tongbi
        rows.append(rec)
    return rows


# ---------------------------------------------------------------------------
# 公告 (announcements)
# ---------------------------------------------------------------------------

_CNINFO_ORGID_MAP: dict[str, str] = {}


def _cninfo_ts_to_date(ts) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
    return str(ts)[:10] if ts else ""


def _cninfo_orgid(code: str) -> str:
    """巨潮 股票->orgId（模块级缓存）。orgId 非统一 ``gssx0{code}`` 格式，动态查官方
    映射表，查不到再回退老格式。"""
    global _CNINFO_ORGID_MAP
    code = normalize_ticker(code)
    if not _CNINFO_ORGID_MAP:
        try:
            r = requests.get(_CNINFO_ORGID_URL, headers={"User-Agent": UA}, timeout=15)
            _CNINFO_ORGID_MAP = {s["code"]: s["orgId"] for s in r.json().get("stockList", [])}
        except Exception as exc:  # noqa: BLE001
            logger.warning("a_stock_data cninfo orgId map fetch failed: %s", exc)
    org = _CNINFO_ORGID_MAP.get(code)
    if org:
        return org
    if code.startswith("6"):
        return f"gssh0{code}"
    if code.startswith(("8", "4")):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def fetch_announcements(code: str, page_size: int = 30) -> list[dict]:
    """巨潮公告全文检索。返回 [{title, type, date, url}]."""
    code = normalize_ticker(code)
    org_id = _cninfo_orgid(code)
    payload = {
        "stock": f"{code},{org_id}", "tabName": "fulltext",
        "pageSize": str(page_size), "pageNum": "1",
        "column": "", "category": "", "plate": "", "seDate": "",
        "searchkey": "", "secid": "", "sortName": "", "sortType": "", "isHLtitle": "true",
    }
    headers = {
        "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.cninfo.com.cn/new/disclosure",
        "Origin": "https://www.cninfo.com.cn",
    }
    try:
        r = requests.post(_CNINFO_QUERY_URL, data=payload, headers=headers, timeout=15)
        anns = r.json().get("announcements", []) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("a_stock_data announcements failed for %s: %s", code, exc)
        return []
    return [
        {
            "title": a.get("announcementTitle", ""),
            "type": a.get("announcementTypeName", ""),
            "date": _cninfo_ts_to_date(a.get("announcementTime")),
            "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={a.get('announcementId', '')}",
        }
        for a in anns
    ]


# ---------------------------------------------------------------------------
# 行情（实时估值）— 腾讯 PE/PB/市值/换手率
# ---------------------------------------------------------------------------


def fetch_quote(codes: list[str]) -> dict[str, dict]:
    """腾讯财经实时行情（GBK，``~`` 分隔）。返回 {code: {name, price, pe_ttm, pb, mcap_yi, ...}}.

    For historical OHLCV use the registered ``a_stock_data`` backtest loader; this
    is the realtime valuation snapshot (PE/PB/市值/换手率/涨跌停) the loader omits."""
    import urllib.request

    prefixed = []
    norm = []
    for c in codes:
        c = normalize_ticker(c)
        norm.append(c)
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")
    try:
        req = urllib.request.Request(_TENCENT_URL + ",".join(prefixed))
        req.add_header("User-Agent", "Mozilla/5.0")
        data = urllib.request.urlopen(req, timeout=10).read().decode("gbk")
    except Exception as exc:  # noqa: BLE001
        logger.warning("a_stock_data tencent quote failed for %s: %s", norm, exc)
        return {}

    result: dict[str, dict] = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue

        def _f(i: int) -> float:
            return float(vals[i]) if vals[i] else 0.0

        result[key[2:]] = {
            "name": vals[1], "price": _f(3), "last_close": _f(4), "open": _f(5),
            "change_pct": _f(32), "high": _f(33), "low": _f(34),
            "turnover_pct": _f(38), "pe_ttm": _f(39), "mcap_yi": _f(44),
            "float_mcap_yi": _f(45), "pb": _f(46), "limit_up": _f(47),
            "limit_down": _f(48), "pe_static": _f(52),
        }
    return result
