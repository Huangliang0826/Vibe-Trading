"""a-stock-data loader: A-share OHLCV via the a-stock-data toolkit's 行情 layer.

Wraps the market-data layer of simonlin1212/a-stock-data (SKILL.md V3.2.2),
honouring its source priority ("能用通达信/腾讯，就别用东财"):

  * **百度股市通** (``finance.pae.baidu.com``) — daily K-line that already carries
    MA5/10/20; HTTP, no IP ban. Primary for ``1D``.
  * **通达信 / mootdx** (TCP 7709) — proven historical path; intraday bars and the
    daily fallback. Reuses the in-repo :mod:`backtest.loaders.mootdx_loader`.

Realtime valuation (PE/PB/市值/换手率 via 腾讯) and the non-OHLCV layers
(研报/新闻/基础数据/公告) live in :mod:`backtest.loaders.a_stock_data_research`.

Scope: A-share OHLCV only (沪/深 auto-detected from symbol). 北交所 (BJ) is skipped
— neither Baidu's stock K-line nor mootdx's std factory serves it reliably; the
fallback chain hands those to akshare/tushare.

``is_available()`` gates on imports only (``requests`` + ``mootdx``); reachability
of the Chinese servers is discovered at fetch time, and an empty result lets the
``a_share`` fallback chain proceed to tushare/mootdx/akshare.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd
import requests

from backtest.loaders._a_stock_data_common import UA, get_prefix, normalize_ticker
from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_OHLCV_COLS = ["open", "high", "low", "close", "volume"]
_BAIDU_KLINE_URL = "https://finance.pae.baidu.com/selfselect/getstockquotation"


def _is_a_share(code: str) -> bool:
    """Accept either an explicit ``.SH/.SZ/.BJ`` suffix or a bare 6-digit ticker."""
    upper = code.upper()
    if upper.endswith((".SH", ".SZ", ".BJ")):
        return True
    return len(code) == 6 and code.isdigit()


def _is_bj(code: str) -> bool:
    """Detect 北交所 symbols (``.BJ`` suffix or 4xxxxx / 8xxxxx bare code)."""
    upper = code.upper()
    if upper.endswith(".BJ"):
        return True
    return len(code) == 6 and code.isdigit() and code[0] in ("4", "8")


@register
class DataLoader:
    """a-stock-data-backed A-share OHLCV loader (Baidu primary, mootdx fallback)."""

    name = "a_stock_data"
    markets = {"a_share"}
    requires_auth = False

    def __init__(self) -> None:
        self._mootdx = None  # lazy backtest.loaders.mootdx_loader.DataLoader

    def is_available(self) -> bool:
        """Available when both ``requests`` and ``mootdx`` import (no network probe)."""
        try:
            import mootdx  # noqa: F401
            import requests  # noqa: F401
            return True
        except ImportError:
            return False

    def _mootdx_loader(self):
        if self._mootdx is None:
            from backtest.loaders.mootdx_loader import DataLoader as MootdxLoader
            self._mootdx = MootdxLoader()
        return self._mootdx

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch A-share OHLCV.

        Args:
            codes: ``.SH/.SZ/.BJ`` suffix or bare 6-digit tickers; non-A-share and
                北交所 symbols are skipped (handed to other loaders by the chain).
            start_date / end_date: ``YYYY-MM-DD``.
            interval: ``1m / 5m / 15m / 30m / 1H / 1D / 1W / 1M``.
            fields: Ignored (OHLCV only).

        Returns:
            Mapping ``symbol -> OHLCV DataFrame`` (``trade_date`` index, columns
            ``[open, high, low, close, volume]``).
        """
        validate_date_range(start_date, end_date)

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            if not _is_a_share(code):
                logger.debug("a_stock_data: skipping non-A-share symbol %s", code)
                continue
            if _is_bj(code):
                logger.warning(
                    "a_stock_data: 北交所 (%s) not served by Baidu/mootdx-std; "
                    "use akshare/tushare", code,
                )
                continue
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda code=code: self._fetch_one(code, start_date, end_date, interval),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:  # noqa: BLE001 — one bad symbol must not sink the batch
                logger.warning("a_stock_data failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str, interval: str,
    ) -> Optional[pd.DataFrame]:
        symbol = normalize_ticker(code)

        # Daily: Baidu first (a-stock-data's signature 行情 source), then mootdx.
        if interval == "1D":
            df = self._fetch_baidu_daily(symbol, start_date, end_date)
            if df is not None and not df.empty:
                return df
            logger.debug("a_stock_data: Baidu empty for %s, falling back to mootdx", symbol)

        # Intraday/weekly/monthly (and the daily fallback) reuse the proven
        # mootdx loader internals so we don't re-derive its frequency mapping.
        return self._mootdx_loader()._fetch_one(symbol, start_date, end_date, interval)

    @staticmethod
    def _fetch_baidu_daily(
        symbol: str, start_date: str, end_date: str,
    ) -> Optional[pd.DataFrame]:
        """百度股市通 daily K-line -> OHLCV contract, clipped to the window.

        Baidu returns ``{"keys": [...], "rows": ["v1,v2,...", ...]}`` where ``rows``
        are comma-separated values aligned to ``keys``. We map by key name (open/
        close/high/low/volume + a date column) and ignore the embedded MA columns.
        Returns ``None`` on any parse/shape problem so the mootdx fallback runs.
        """
        prefix = get_prefix(symbol)
        params = {
            "all": "1", "isIndex": "false", "isBk": "false", "isBlock": "false",
            "isFutures": "false", "isStock": "true", "newFormat": "1",
            "group": "quotation_kline_ab", "finClientType": "pc",
            "code": symbol, "start_time": f"{start_date} 00:00:00", "ktype": "1",
        }
        headers = {
            "User-Agent": UA,
            "Accept": "application/vnd.finance-web.v1+json",
            "Origin": "https://gushitong.baidu.com",
            "Referer": "https://gushitong.baidu.com/",
        }
        try:
            r = requests.get(_BAIDU_KLINE_URL, params=params, headers=headers, timeout=15)
            md = (r.json().get("Result", {}) or {}).get("newMarketData", {}) or {}
        except Exception as exc:  # noqa: BLE001 — fall through to mootdx
            logger.debug("a_stock_data: Baidu request/parse failed for %s%s: %s", prefix, symbol, exc)
            return None

        keys = md.get("keys") or []
        raw_rows = [row for row in (md.get("marketData", "") or "").split(";") if row]
        if not keys or not raw_rows:
            return None

        records = [dict(zip(keys, row.split(","))) for row in raw_rows]
        df = pd.DataFrame(records)

        date_col = next((c for c in ("time", "timestamp", "date") if c in df.columns), None)
        if date_col is None or not set(_OHLCV_COLS).issubset(df.columns):
            logger.debug("a_stock_data: Baidu columns unexpected for %s: %s", symbol, list(df.columns))
            return None

        df["trade_date"] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=["trade_date"]).set_index("trade_date").sort_index()
        for col in _OHLCV_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[_OHLCV_COLS].dropna(subset=["open", "high", "low", "close"])

        end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df.loc[pd.Timestamp(start_date):end_ts]
        return df if not df.empty else None
