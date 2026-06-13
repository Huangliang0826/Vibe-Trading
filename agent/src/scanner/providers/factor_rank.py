"""factor_rank: rank the cross-section by a whitelist of strict-bench factors."""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.scanner.core import Candidate
from src.scanner.providers.base import SignalProvider


def _asof_row(frame: pd.DataFrame, asof: str) -> pd.Series | None:
    """Last row at or before ``asof``; None if the frame has no such row."""
    if frame is None or frame.empty:
        return None
    idx = pd.to_datetime(frame.index)
    cutoff = pd.Timestamp(asof)
    mask = idx <= cutoff
    if not mask.any():
        return None
    return frame.loc[mask].iloc[-1]


FACTOR_LABELS: dict[str, str] = {
    # alpha101 (Kakushadze)
    "alpha101_005": "VWAP偏离动量",
    "alpha101_007": "放量趋势跟踪",
    "alpha101_009": "条件价格反转",
    "alpha101_011": "VWAP偏离×量变",
    "alpha101_012": "量价背离",
    "alpha101_021": "均值回归",
    "alpha101_024": "条件反转",
    "alpha101_025": "高位放量回落",
    "alpha101_026": "量价秩相关",
    "alpha101_030": "量缩价变",
    "alpha101_032": "均线偏离+VWAP滞后",
    "alpha101_033": "开收比反转",
    "alpha101_034": "波动率收敛+价格反转",
    "alpha101_035": "量×价格区间×收益反转",
    "alpha101_036": "多因子加权",
    "alpha101_037": "隔日缺口+价量相关",
    "alpha101_038": "收盘排名×日内涨幅",
    "alpha101_043": "放量下跌反转",
    "alpha101_047": "高价放量回落",
    "alpha101_049": "加速下跌反转",
    "alpha101_051": "条件动量切换",
    "alpha101_054": "低位阴线强度",
    "alpha101_057": "VWAP偏离衰减",
    "alpha101_083": "波幅×量排名",
    # gtja191
    "gtja191_002": "高低价差动量",
    "gtja191_004": "条件止损信号",
    "gtja191_005": "量价秩相关极值",
    "gtja191_034": "12日均线偏离",
    "gtja191_046": "多周期均线比",
    "gtja191_048": "连续涨跌×缩量",
    "gtja191_065": "6日均线偏离",
    "gtja191_080": "5日量变速率",
    "gtja191_085": "放量下跌反转",
    "gtja191_091": "近期高点回落×量价相关",
    "gtja191_102": "量变平滑动量",
    "gtja191_111": "量价波动交叉",
    "gtja191_117": "收益波动×量排名",
    "gtja191_171": "日内偏离×均线",
    "gtja191_180": "量变均值回归",
    "gtja191_184": "收益与收盘偏离相关",
    # qlib158
    "qlib158_ma5": "5日均线偏离",
    "qlib158_ma10": "10日均线偏离",
    "qlib158_qtld5": "5日下分位支撑",
    "qlib158_qtld10": "10日下分位支撑",
    "qlib158_qtlu5": "5日上分位压力",
    "qlib158_qtlu10": "10日上分位压力",
    "qlib158_vsumd5": "5日量能涨跌差",
    "qlib158_vsump5": "5日量能上涨占比",
}


def _label(factor_id: str) -> str:
    return FACTOR_LABELS.get(factor_id, factor_id)


class FactorRankProvider(SignalProvider):
    """Composite cross-sectional rank over whitelisted factors, weighted by |IR|."""

    provider_id = "factor_rank"

    def __init__(self, manifest: dict[str, Any], registry: Any, top_n: int = 20):
        self._factors = list(manifest.get("factors", []))
        self._registry = registry
        self._top_n = top_n

    def compute(self, panel: dict[str, pd.DataFrame], asof: str) -> list[Candidate]:
        if not self._factors:
            return []

        weighted = pd.Series(dtype=float)
        total_weight = 0.0
        contributions: dict[str, dict[str, float]] = {}

        for f in self._factors:
            ir = float(f.get("ir", 0.0))
            weight = abs(ir)
            if weight == 0.0:
                continue
            try:
                factor_df = self._registry.compute(f["id"], panel)
            except Exception:  # noqa: BLE001 — a broken factor must not sink the scan
                continue
            row = _asof_row(factor_df, asof)
            if row is None:
                continue
            row = row.dropna()
            if row.empty:
                continue
            # Percentile rank in [0,1]; sign(ir) flips negative-IR factors.
            pct = row.rank(pct=True)
            signed = pct if ir >= 0 else (1.0 - pct)
            contrib = signed * weight
            weighted = weighted.add(contrib, fill_value=0.0)
            total_weight += weight
            for sym, val in contrib.items():
                contributions.setdefault(str(sym), {})[str(f["id"])] = float(val)

        if total_weight == 0.0 or weighted.empty:
            return []

        composite = (weighted / total_weight) * 100.0
        ranked = composite.sort_values(ascending=False)

        out: list[Candidate] = []
        for sym, score in ranked.head(self._top_n).items():
            # Normalise each factor's raw contribution by total weight and scale
            # to 0-100 so the per-factor detail sums to the composite score.
            # NOTE: a symbol absent from a factor's cross-section contributes 0 to
            # that factor (NaN-union via fill_value=0.0) while still dividing by
            # the full total_weight — i.e. partial coverage is an intentional
            # penalty, not an abstention.
            raw = contributions.get(str(sym), {})
            detail = {
                _label(fid): round(v / total_weight * 100.0, 2)
                for fid, v in raw.items()
            }
            detail = dict(sorted(detail.items(), key=lambda kv: -kv[1]))
            top_names = list(detail.keys())[:2]
            attribution = (
                "、".join(top_names) + " 驱动" if top_names else "综合因子排名"
            )
            out.append(Candidate(
                symbol=str(sym),
                score=round(float(score), 2),
                provider_id=self.provider_id,
                attribution=attribution,
                detail=detail,
            ))
        return out
