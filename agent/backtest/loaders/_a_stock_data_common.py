"""Shared helpers for the a-stock-data integration (行情 loader + research module).

Ported from simonlin1212/a-stock-data (SKILL.md V3.2.2). The single load-bearing
piece here is :func:`em_get` — a process-global, rate-limited entry point for every
East Money (``eastmoney.com``) HTTP request. East Money throttles aggressively
(>5 req/s, >=10 concurrent, or >=200 req/min trips a temporary IP ban), so the
OHLCV loader and the research helpers MUST funnel their East Money calls through
the same module-level limiter rather than each keeping its own budget.

Non-East Money sources (mootdx TCP, 腾讯 qt.gtimg.cn, 百度 finance.pae.baidu.com,
新浪 quotes.sina.cn, 巨潮 cninfo.com.cn) are not IP-banned in practice and do not
need the throttle.
"""

from __future__ import annotations

import random
import time

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── East Money 防封：进程级串行限流 + 会话复用 ────────────────────────────────
# All eastmoney.com requests share one Keep-Alive session and one inter-request
# spacing budget. ``EM_MIN_INTERVAL`` is the floor between two consecutive East
# Money calls; bump it (1.5~2s) for large batch screens.
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]  # module-level mutable timestamp (shared across importers)


def em_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    **kwargs,
):
    """Rate-limited East Money GET. Route every eastmoney.com call through this.

    Sleeps off any remaining ``EM_MIN_INTERVAL`` budget (plus a little jitter)
    before firing, then records the call time even on failure so a raised
    request still spaces out the next one.
    """
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def normalize_ticker(code: str) -> str:
    """Normalize any accepted A-share symbol form to a bare 6-digit code.

    Accepts ``688017`` / ``SH688017`` / ``688017.SH`` / ``sz000001`` / ``BJ832000``
    (case-insensitive). Returns the 6-digit core; non-conforming input is returned
    upper-cased and unchanged so callers can decide to skip it.
    """
    s = code.strip().upper()
    if "." in s:  # 688017.SH
        s = s.split(".")[0]
    elif s[:2] in {"SH", "SZ", "BJ"} and s[2:].isdigit():  # SH688017
        s = s[2:]
    return s


def get_prefix(code: str) -> str:
    """6-digit code -> 通达信/腾讯 market prefix (``sh`` / ``sz`` / ``bj``)."""
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"
