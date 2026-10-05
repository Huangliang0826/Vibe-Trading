"""个人成长:状态读写。

存在后端而不是浏览器 localStorage,是因为打卡多半发生在手机上、回顾多半发生
在电脑上。存在浏览器里会把同一个人的数据劈成互不相干的两份,"两周后看到
进步"直接作废。

状态转换(``apply_checkin`` 等)写成纯函数:进出都是 dict,不碰磁盘,便于测试。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config.paths import get_runtime_root
from src.growth.plan import DOMAINS, PLAN_VERSION

STATE_VERSION = 1


def state_path() -> Path:
    return get_runtime_root() / "growth" / "state.json"


def read_state() -> Optional[dict]:
    """返回已保存的计划;尚未创建或文件损坏时返回 None。"""
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None
    return data


def write_state(state: dict) -> dict:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return state


def clear_state() -> None:
    try:
        state_path().unlink()
    except OSError:
        pass


# ── 纯状态转换 ────────────────────────────────────────────────────────────────

def new_state(*, plan: dict, intake: dict, chronotype: str, today: str) -> dict:
    return {
        "version": STATE_VERSION,
        "plan_version": PLAN_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": today,
        "chronotype": chronotype,
        "intake": intake,
        "plan": plan,
        "checkins": [],
        "checkpoints": {},
    }


def apply_checkin(
    state: dict, *, domain: str, today: str, feeling: Optional[int] = None, note: str = "",
) -> dict:
    """记录一次完成,返回新的 state。

    同一领域同一天只推进一步。重复点击推进两步会把当天的内容悄悄跳过去——
    这正是手机上最容易误触出来的情况,所以在这里挡掉而不是靠界面。

    但当天已有记录时并非什么都不做:感受和备注会写进那一条。界面上"感觉如何"
    是打完卡之后才出现的,若这里原样返回,那几个按钮就永远存不下东西。
    """
    if domain not in DOMAINS:
        raise ValueError(f"未知领域:{domain}")
    if domain not in (state.get("plan") or {}):
        raise ValueError(f"计划里没有这个领域:{domain}")

    checkins = list(state.get("checkins") or [])
    existing = next(
        (i for i, c in enumerate(checkins)
         if c.get("domain") == domain and c.get("date") == today),
        None,
    )
    if existing is not None:
        if feeling is None and not note.strip():
            return state  # 纯重复点击:保持幂等
        updated = dict(checkins[existing])
        if feeling is not None:
            updated["feeling"] = max(1, min(3, int(feeling)))
        if note.strip():
            updated["note"] = note.strip()[:80]
        checkins[existing] = updated
        return {**state, "checkins": checkins}

    steps = (state["plan"][domain].get("steps") or [])
    done = sum(1 for c in checkins if c.get("domain") == domain)
    if done >= len(steps):
        return state  # 本领域已全部完成

    entry = {"date": today, "domain": domain, "day": steps[done]["day"]}
    if feeling is not None:
        entry["feeling"] = max(1, min(3, int(feeling)))
    if note.strip():
        entry["note"] = note.strip()[:80]

    return {**state, "checkins": [*checkins, entry]}


def undo_checkin(state: dict, *, domain: str, today: str) -> dict:
    """撤销今天这一次——手机上误触是常事,不给撤销就只能眼看着进度错位。"""
    checkins = [
        c for c in (state.get("checkins") or [])
        if not (c.get("domain") == domain and c.get("date") == today)
    ]
    return {**state, "checkins": checkins}


def set_checkpoint(state: dict, *, domain: str, which: str, value: str) -> dict:
    """记录检查点的基线(start)或两周后的结果(end)。"""
    if which not in ("start", "end"):
        raise ValueError("检查点只能是 start 或 end")
    marks = {**(state.get("checkpoints") or {})}
    marks[domain] = {**(marks.get(domain) or {}), which: value.strip()[:120]}
    return {**state, "checkpoints": marks}
