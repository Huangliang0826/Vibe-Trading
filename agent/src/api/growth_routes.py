"""个人成长路由:每天的目标 + 各语言的练习。

每门语言的练习完全共用一套引擎,所以这里只有一组端点,语言和分类都是参数。
「每天」不再有 AI 排的计划——它的两项就是两门语言当天的测验目标,完成与否
由实际答对的条数决定,而不是由谁按了按钮。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from src.growth.catalog import LEVELS as _LEVELS
from src.growth.languages import CATALOGS, DEFAULT_LANG, catalog, languages
from src.growth.practice import (
    FAST_MS, MAX_BOX, QUIZ_OPTIONS, build_session, default_track, favorites, find_pattern,
    goal_days, mark_studied, pick_quiz, record_answer, set_favorite, stats,
    today_progress,
)
from src.growth.progress import build_calendar, build_summary
from src.growth.rewards import build_rewards, level_of, mastered_count
from src.growth.store import clear_state, empty_state, read_state, write_state

logger = logging.getLogger(__name__)
AuthDep = Callable[..., Awaitable[Any] | Any]


def _today() -> str:
    return date.today().isoformat()


class StudiedRequest(BaseModel):
    pattern_id: str = Field(..., max_length=64)


class FavoriteRequest(BaseModel):
    pattern_id: str = Field(..., max_length=64)
    favorite: bool = True


class AnswerRequest(BaseModel):
    """一次测验作答。对错由服务端判,客户端只报选了哪张卡和用了多久。"""
    pattern_id: str = Field(..., max_length=64)
    chosen_id: str = Field(..., max_length=64)
    elapsed_ms: int = Field(0, ge=0, le=600_000)


def register_growth_routes(app: FastAPI, *, require_auth: AuthDep) -> None:
    router = APIRouter(prefix="/growth", tags=["growth"], dependencies=[Depends(require_auth)])

    def _require_lang(lang: str) -> str:
        if lang not in CATALOGS:
            raise HTTPException(status_code=400, detail=f"未知的语言:{lang}")
        return lang

    def _require_track(lang: str, track: str) -> str:
        if track not in catalog(lang).by_track:
            raise HTTPException(status_code=400, detail=f"未知的分类:{track}")
        return track

    def _lang_of(pattern_id: str) -> str:
        """按 id 操作的端点不带语言参数——id 全局唯一,从条目本身取。"""
        pattern = find_pattern(pattern_id)
        return pattern.lang if pattern else DEFAULT_LANG

    def _practice_payload(lang: str, track: str, doc: dict) -> dict:
        today = _today()
        reviews = doc.get("reviews") or {}
        cat = catalog(lang)
        return {
            "today": today,
            "lang": lang,
            "track": track,
            "languages": languages(),
            "tracks": [{"key": t, "label": cat.by_track[t][0].track_label,
                        "total": cat.track_totals[t]} for t in cat.tracks],
            "session": build_session(reviews, today, lang=lang, track=track),
            "stats": stats(reviews, today, lang, track),
            "today_progress": today_progress(doc, today, lang),
            "level": level_of(mastered_count(reviews)),
            "favorites": favorites(reviews, lang, track),
            "fast_ms": FAST_MS,
            "groups": cat.groups(track),
            "levels": [{"key": k, "label": v, "total": n}
                       for (k, v), n in zip(_LEVELS.items(), cat.level_totals(track).values())],
        }

    # ── 每天 ──────────────────────────────────────────────────────────────────

    @router.get("/state")
    async def state():
        """今天两门语言的目标 + 打卡日历。没有计划,也就没有"还没配置"这回事。"""
        today = _today()
        docs = {lang: read_state(lang) for lang in CATALOGS}
        days = {lang: goal_days(doc, lang) for lang, doc in docs.items()}
        summary = build_summary(days, today)
        return {
            "today": today,
            "rewards": build_rewards(docs, days),
            "languages": [
                {"key": lang, "label": catalog(lang).label,
                 **today_progress(docs[lang], today, lang)}
                for lang in CATALOGS
            ],
            "done_today": sum(1 for lang in CATALOGS
                              if today_progress(docs[lang], today, lang)["done"]),
            "lang_count": len(CATALOGS),
            "streak": summary["streak"],
            "calendar": build_calendar(days, today),
            "summary": summary,
        }

    # ── 练习 ──────────────────────────────────────────────────────────────────

    @router.get("/practice")
    async def practice(lang: str = Query(DEFAULT_LANG, max_length=8),
                       track: str = Query("", max_length=16)):
        _require_lang(lang)
        track = _require_track(lang, track or default_track(lang))
        return _practice_payload(lang, track, read_state(lang))

    @router.get("/practice/catalog")
    async def practice_catalog(lang: str = Query(DEFAULT_LANG, max_length=8),
                               track: str = Query("", max_length=16)):
        _require_lang(lang)
        track = _require_track(lang, track or default_track(lang))
        cat = catalog(lang)
        reviews = read_state(lang).get("reviews") or {}
        return {
            "groups": cat.groups(track),
            "levels": [{"key": k, "label": v, "total": n}
                       for (k, v), n in zip(_LEVELS.items(), cat.level_totals(track).values())],
            "patterns": [
                {**p.to_dict(), "box": int((reviews.get(p.id) or {}).get("box", -1))}
                for p in cat.by_track[track]
            ],
        }

    @router.post("/practice/studied")
    async def practice_studied(payload: StudiedRequest):
        """学习页看过一条。只记接触,不打分——打分是测验的事。"""
        lang = _lang_of(payload.pattern_id)
        doc = read_state(lang)
        try:
            reviews = mark_studied(doc.get("reviews") or {}, payload.pattern_id, _today())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved = write_state(lang, {**doc, "reviews": reviews})
        pattern = find_pattern(payload.pattern_id)
        return _practice_payload(lang, pattern.track, saved)

    @router.post("/practice/favorite")
    async def practice_favorite(payload: FavoriteRequest):
        lang = _lang_of(payload.pattern_id)
        doc = read_state(lang)
        try:
            reviews = set_favorite(doc.get("reviews") or {}, payload.pattern_id, payload.favorite)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved = write_state(lang, {**doc, "reviews": reviews})
        pattern = find_pattern(payload.pattern_id)
        return _practice_payload(lang, pattern.track, saved)

    @router.get("/practice/quiz")
    async def practice_quiz(lang: str = Query(DEFAULT_LANG, max_length=8),
                            track: str = Query("", max_length=16),
                            count: int = Query(20, ge=1, le=100)):
        """抽一批两选一的题。"""
        _require_lang(lang)
        track = _require_track(lang, track or default_track(lang))
        doc = read_state(lang)
        reviews = doc.get("reviews") or {}
        return {
            "questions": pick_quiz(reviews, _today(), lang=lang, track=track, count=count),
            "options_per_question": QUIZ_OPTIONS,
            "fast_ms": FAST_MS,
            "lang": lang,
            "track": track,
            "stats": stats(reviews, _today(), lang, track),
            "today_progress": today_progress(doc, _today(), lang),
        }

    @router.post("/practice/answer")
    async def practice_answer(payload: AnswerRequest):
        """判一次作答并推进盒子。对错在服务端判,客户端报不了"我对了"。"""
        correct = payload.chosen_id == payload.pattern_id
        today = _today()
        lang = _lang_of(payload.pattern_id)
        read_before = read_state(lang)
        try:
            doc = record_answer(read_before, payload.pattern_id, correct,
                                payload.elapsed_ms, today)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        before = (read_before.get("reviews") or {}).get(payload.pattern_id) or {}
        after = doc["reviews"][payload.pattern_id]
        write_state(lang, doc)
        pattern = find_pattern(payload.pattern_id)
        return {
            "correct": correct,
            # 即时反馈要说清"这一下换来了什么":升了一盒,还是刚刚推到最后一盒。
            "box": int(after.get("box", 0)),
            "box_up": int(after.get("box", 0)) > int(before.get("box", 0)),
            "just_mastered": (int(after.get("box", 0)) >= MAX_BOX
                              > int(before.get("box", 0))),
            "grade": (doc["reviews"][payload.pattern_id] or {}).get("last_grade", ""),
            "stats": stats(doc["reviews"], today, lang, pattern.track),
            "today_progress": today_progress(doc, today, lang),
        }

    @router.post("/practice/reset")
    async def practice_reset(lang: str = Query(DEFAULT_LANG, max_length=8),
                             track: str = Query("", max_length=16)):
        _require_lang(lang)
        track = _require_track(lang, track or default_track(lang))
        clear_state(lang)
        return _practice_payload(lang, track, empty_state())

    app.include_router(router)
