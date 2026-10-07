"""一门语言的练习清单:条目、分类、分组、难度。

英语和荷兰语共用同一套练习引擎(检索练习 + 间隔重复 + 两选一测验),不同的
只有内容。所以把"内容长什么样"抽到这里,各语言只提供自己的数据。

分类(track)按**失败方式**划分,而不是按词性:

* ``frame`` 句型——要接自己的内容,用错只是话接不顺;
* ``oneliner`` 整句——拿来即用,不会就是接不上话;
* ``collocation`` 搭配——嵌在句子里,用错语法全对但一听就不是母语者。

每门语言用得上哪几类由它自己决定:零基础的荷兰语先不做话语框架。
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 难度。清单顺序即引入顺序,所以每条线内部按这个排序,梯度自动成立。
LEVELS = {"core": "基础", "mid": "中级", "high": "高级"}
_LEVEL_ORDER = list(LEVELS)

TRACK_LABELS = {"frame": "句型", "oneliner": "整句", "collocation": "搭配"}


@dataclass(frozen=True)
class Pattern:
    id: str
    #: 要练的那段外语。句型里带省略号表示有空位要填。
    frame: str
    group: str
    level: str
    meaning: str
    #: 中文情境提示。练习时只显示这个,外语要自己产出,所以里面不能出现外语。
    cue: str
    examples: tuple[str, ...]
    #: 例句的中文翻译,与 ``examples`` 一一对应。零基础的语言必须给——
    #: 看不懂的例句等于没有例句。会的语言可以留空。
    example_meanings: tuple[str, ...] = ()
    lang: str = "en"
    track: str = "frame"
    #: 直译版,用作测验干扰项。只有搭配才有。
    wrong: tuple[str, ...] = ()
    group_label: str = ""

    @property
    def level_label(self) -> str:
        return LEVELS[self.level]

    @property
    def track_label(self) -> str:
        return TRACK_LABELS[self.track]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "frame": self.frame, "group": self.group,
            "group_label": self.group_label, "level": self.level,
            "level_label": self.level_label, "meaning": self.meaning,
            "cue": self.cue,
            "examples": [
                {"text": text, "meaning": meaning}
                for text, meaning in zip(
                    self.examples,
                    [*self.example_meanings, *([""] * len(self.examples))],
                )
            ],
            "lang": self.lang, "track": self.track, "track_label": self.track_label,
        }


@dataclass(frozen=True)
class Catalog:
    """一门语言的全部内容,以及按分类/id 的索引。"""

    lang: str
    label: str
    patterns: tuple[Pattern, ...]
    #: 这门语言实际用到的分类,顺序即界面上的顺序。
    tracks: tuple[str, ...]

    by_id: dict[str, Pattern] = field(default_factory=dict)
    by_track: dict[str, tuple[Pattern, ...]] = field(default_factory=dict)

    @property
    def track_totals(self) -> dict[str, int]:
        return {t: len(self.by_track[t]) for t in self.tracks}

    def level_totals(self, track: str) -> dict[str, int]:
        return {lv: sum(1 for p in self.by_track[track] if p.level == lv) for lv in LEVELS}

    def groups(self, track: str) -> list[dict]:
        """该分类用到的分组,按首次出现的顺序。"""
        seen: dict[str, str] = {}
        for p in self.by_track[track]:
            seen.setdefault(p.group, p.group_label)
        return [{"key": k, "label": v} for k, v in seen.items()]


def build_catalog(lang: str, label: str, tracks: tuple[str, ...],
                  patterns: list[Pattern]) -> Catalog:
    """按分类分组并在每条线内部按难度排序。

    不排的话第一天就会撞上高级内容——清单顺序就是新内容的引入顺序。
    """
    by_track = {
        track: tuple(sorted((p for p in patterns if p.track == track),
                            key=lambda p: _LEVEL_ORDER.index(p.level)))
        for track in tracks
    }
    ordered = tuple(p for track in tracks for p in by_track[track])
    return Catalog(
        lang=lang, label=label, patterns=ordered, tracks=tracks,
        by_id={p.id: p for p in ordered}, by_track=by_track,
    )
