"""Stable display metadata for scanner universes."""
from __future__ import annotations

from dataclasses import replace

from src.scanner.core import ScanResult

HSTECH_COMPANY_NAMES = {
    "700.HK": "腾讯控股",
    "9988.HK": "阿里巴巴-W",
    "3690.HK": "美团-W",
    "9999.HK": "网易-S",
    "981.HK": "中芯国际",
    "9618.HK": "京东集团-SW",
    "1810.HK": "小米集团-W",
    "268.HK": "金蝶国际",
    "3888.HK": "金山软件",
    "9888.HK": "百度集团-SW",
    "1024.HK": "快手-W",
    "2018.HK": "瑞声科技",
    "6060.HK": "众安在线",
    "241.HK": "阿里健康",
    "2382.HK": "舜宇光学科技",
    "285.HK": "比亚迪电子",
    "992.HK": "联想集团",
    "6618.HK": "京东健康",
    "9626.HK": "哔哩哔哩-W",
    "9698.HK": "万国数据-SW",
    "1347.HK": "华虹半导体",
    "2015.HK": "理想汽车-W",
    "9868.HK": "小鹏汽车-W",
    "9866.HK": "蔚来-SW",
    "780.HK": "同程旅行",
    "9961.HK": "携程集团-S",
    "9901.HK": "新东方-S",
    "2013.HK": "微盟集团",
    "772.HK": "阅文集团",
    "909.HK": "明源云",
}


def attach_company_names(result: ScanResult) -> ScanResult:
    """Add names to HSTECH candidates, including legacy stored scans."""
    if result.universe != "hstech":
        return result
    candidates = [
        replace(candidate, company_name=candidate.company_name or HSTECH_COMPANY_NAMES.get(candidate.symbol))
        for candidate in result.candidates
    ]
    return replace(result, candidates=candidates)
