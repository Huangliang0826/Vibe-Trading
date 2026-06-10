"""Tests for the a_stock_data research helpers (研报/新闻/基础数据/公告/估值, no network)."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import backtest.loaders.a_stock_data_research as research


def _resp(json_obj=None, text=None):
    return SimpleNamespace(json=lambda: json_obj, text=text)


@pytest.fixture
def record_em_get(monkeypatch: pytest.MonkeyPatch):
    """Replace the shared em_get with a recorder returning a queued response."""
    calls: list[tuple] = []
    box = {"resp": _resp({})}

    def fake_em_get(url, params=None, headers=None, timeout=15, **kwargs):
        calls.append((url, params))
        return box["resp"]

    monkeypatch.setattr(research, "em_get", fake_em_get)
    return calls, box


# ---------------------------------------------------------------------------
# 研报
# ---------------------------------------------------------------------------


def test_fetch_reports_uses_em_get_and_normalizes_code(record_em_get) -> None:
    calls, box = record_em_get
    box["resp"] = _resp({"data": [{"title": "买入", "publishDate": "2025-01-02",
                                    "orgSName": "某券商", "infoCode": "AB"}],
                         "TotalPage": 1})
    out = research.fetch_reports("688017.SH", with_eps_forecast=False)
    assert out["reports"][0]["title"] == "买入"
    assert out["eps_forecast"] == []
    # em_get is the throttle path; code normalized to bare 6-digit.
    assert calls and calls[0][1]["code"] == "688017"


def test_fetch_reports_includes_eps_forecast(record_em_get, monkeypatch) -> None:
    _, box = record_em_get
    box["resp"] = _resp({"data": [], "TotalPage": 1})
    monkeypatch.setattr(
        research, "ths_eps_forecast",
        lambda code: pd.DataFrame({"年度": [2025], "均值": [3.1]}),
    )
    out = research.fetch_reports("600519")
    assert out["eps_forecast"] == [{"年度": 2025, "均值": 3.1}]


# ---------------------------------------------------------------------------
# 新闻
# ---------------------------------------------------------------------------


def test_fetch_news_stock_parses_jsonp(record_em_get) -> None:
    calls, box = record_em_get
    payload = '{"result":{"cmsArticleWebOld":[{"title":"<b>大涨</b>","content":"x","date":"2025-01-02 10:00","mediaName":"东财","url":"http://e"}]}}'
    box["resp"] = _resp(text=f"jQuery_news({payload})")
    rows = research.fetch_news("000001.SZ")
    assert rows[0]["title"] == "大涨"  # HTML stripped
    assert rows[0]["source"] == "东财"
    assert calls[0][0] == research._STOCK_NEWS_URL


def test_fetch_news_global_when_no_code(record_em_get) -> None:
    calls, box = record_em_get
    box["resp"] = _resp({"data": {"fastNewsList": [
        {"title": "快讯", "summary": "摘要", "showTime": "2025-01-02 09:00"}]}})
    rows = research.fetch_news()
    assert rows[0]["title"] == "快讯"
    assert calls[0][0] == research._GLOBAL_NEWS_URL


# ---------------------------------------------------------------------------
# 基础数据
# ---------------------------------------------------------------------------


def test_fetch_stock_info(record_em_get) -> None:
    calls, box = record_em_get
    box["resp"] = _resp({"data": {"f57": "600519", "f58": "贵州茅台", "f127": "白酒",
                                   "f84": 1.2e9, "f116": 2.1e12, "f189": 20010827}})
    info = research.fetch_stock_info("600519")
    assert info["name"] == "贵州茅台"
    assert info["industry"] == "白酒"
    assert info["list_date"] == "20010827"
    # 600xxx -> market_code 1
    assert calls[0][1]["secid"] == "1.600519"


def test_fetch_financials_parses_sina_report_list(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"result": {"data": {"report_list": {
        "20250331": {"data": [{"item_title": "净利润", "item_value": "100",
                               "item_tongbi": "5%"}]},
        "20241231": {"data": [{"item_title": "净利润", "item_value": "380"}]},
    }}}}
    monkeypatch.setattr(research.requests, "get", lambda *a, **k: _resp(payload))
    rows = research.fetch_financials("600519", "lrb")
    assert rows[0]["报告期"] == "2025-03-31"  # newest first
    assert rows[0]["净利润"] == "100"
    assert rows[0]["净利润_同比"] == "5%"


# ---------------------------------------------------------------------------
# 公告
# ---------------------------------------------------------------------------


def test_fetch_announcements(monkeypatch: pytest.MonkeyPatch) -> None:
    research._CNINFO_ORGID_MAP = {}  # reset module cache
    monkeypatch.setattr(
        research.requests, "get",
        lambda *a, **k: _resp({"stockList": [{"code": "688017", "orgId": "9900041602"}]}),
    )
    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None, **kwargs):
        captured["stock"] = data["stock"]
        return _resp({"announcements": [
            {"announcementTitle": "年报", "announcementTypeName": "定期报告",
             "announcementTime": 1735776000000, "announcementId": "123"}]})

    monkeypatch.setattr(research.requests, "post", fake_post)
    rows = research.fetch_announcements("688017.SH")
    assert rows[0]["title"] == "年报"
    assert rows[0]["url"].endswith("annoId=123")
    # Dynamic orgId resolved from the cninfo map.
    assert captured["stock"] == "688017,9900041602"


# ---------------------------------------------------------------------------
# 实时估值（腾讯）
# ---------------------------------------------------------------------------


def test_fetch_quote_parses_tencent_gbk(monkeypatch: pytest.MonkeyPatch) -> None:
    fields = [""] * 53
    fields[1] = "贵州茅台"
    fields[3] = "1500.0"
    fields[39] = "30.5"   # PE TTM
    fields[44] = "18000"  # mcap 亿
    fields[46] = "9.8"    # PB
    line = 'v_sh600519="' + "~".join(fields) + '";'

    class _FakeResp:
        def read(self):
            return line.encode("gbk")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp())

    out = research.fetch_quote(["600519"])
    assert out["600519"]["name"] == "贵州茅台"
    assert out["600519"]["pe_ttm"] == 30.5
    assert out["600519"]["pb"] == 9.8
    assert out["600519"]["mcap_yi"] == 18000.0
