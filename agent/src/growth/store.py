"""个人成长:练习进度的读写。

存在后端而不是浏览器 localStorage,是因为打卡多半发生在手机上、回顾多半发生
在电脑上。存在浏览器里会把同一个人的数据劈成互不相干的两份。

每门语言一个文件(英语沿用原来的 ``english.json``,已有记录不受影响)。
``reviews`` 是每条内容的复习状态,``daily`` 是每天的作答战绩——日历和"累计
学了多少天"需要按天的数字,而复习状态里只留得下最后一次作答的日期。两份
数据**在同一个文件里一次写完**:分成两次写就会出现只写成功一半的时刻。

状态转换写成纯函数:进出都是 dict,不碰磁盘,便于测试。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.config.paths import get_runtime_root
from src.growth.languages import STATE_FILENAMES

STATE_VERSION = 1


def state_path(lang: str) -> Path:
    return get_runtime_root() / "growth" / STATE_FILENAMES[lang]


def empty_state() -> dict:
    return {"reviews": {}, "daily": {}}


def read_state(lang: str) -> dict:
    try:
        data = json.loads(state_path(lang).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(data, dict):
        return empty_state()
    reviews = data.get("reviews")
    daily = data.get("daily")
    return {
        "reviews": reviews if isinstance(reviews, dict) else {},
        "daily": daily if isinstance(daily, dict) else {},
    }


def write_state(lang: str, doc: dict) -> dict:
    path = state_path(lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": STATE_VERSION, **doc}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return doc


def clear_state(lang: str) -> None:
    try:
        state_path(lang).unlink()
    except OSError:
        pass
