"""注册表:应用支持哪几门语言,各自的清单和每日目标。

加一门语言只要在这里多一行——引擎(检索练习、间隔重复、两选一测验)完全共用。
"""

from __future__ import annotations

from src.growth.catalog import Catalog
from src.growth.dutch_patterns import DUTCH
from src.growth.english_patterns import ENGLISH

CATALOGS: dict[str, Catalog] = {"en": ENGLISH, "nl": DUTCH}
DEFAULT_LANG = "en"

#: 每天在测验里答对多少条算今天过了。荷兰语是零基础起步,定得低一些——
#: 门槛太高,第一周就会放弃。
DAILY_GOALS = {"en": 10, "nl": 6}

#: 进度各自存一个文件。英语沿用原来的文件名,已有的练习记录不受影响。
STATE_FILENAMES = {"en": "english.json", "nl": "dutch.json"}


def catalog(lang: str) -> Catalog:
    if lang not in CATALOGS:
        raise ValueError(f"未知的语言:{lang}")
    return CATALOGS[lang]


def daily_goal(lang: str) -> int:
    return DAILY_GOALS[lang]


def languages() -> list[dict]:
    return [
        {"key": lang, "label": cat.label, "goal": DAILY_GOALS[lang],
         "tracks": [{"key": t, "label": cat.by_track[t][0].track_label,
                     "total": cat.track_totals[t]} for t in cat.tracks]}
        for lang, cat in CATALOGS.items()
    ]
