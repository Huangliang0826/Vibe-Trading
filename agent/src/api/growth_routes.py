"""个人成长 · 计划生成与每日打卡路由。

四个领域(睡眠/健身/荷兰语/英语)共用一份状态,存在后端而不是浏览器,
这样手机上打卡、电脑上回顾看到的是同一份数据。

计划生成按领域并发调用模型;任一领域失败由 ``generate_domain_plan`` 自行退回
确定性兜底计划,所以这个接口不会因为模型不可用而失败。
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from src.growth.plan import (
    CHRONOTYPES, DOMAIN_LABELS, DOMAINS, LEVELS, MINUTE_CHOICES, PLAN_DAYS,
    DomainIntake, Intake, fallback_plan, generate_domain_plan,
)
from src.growth.english import (
    DAILY_GOAL, FAST_MS, QUIZ_OPTIONS, build_session, english_days, english_today,
    favorites, mark_studied, pick_quiz, record_answer, set_favorite, stats,
)
# 别名:``LEVELS`` 在 plan 里是每个领域的起点选项,同名导入会把它整个盖掉。
from src.growth.english_patterns import LEVELS as ENGLISH_LEVELS
from src.growth.english_patterns import GROUPS, LEVEL_TOTALS, PATTERNS
from src.growth.progress import build_overview
from src.growth.store import (
    apply_checkin, clear_english, clear_state, empty_english, new_state,
    read_english, read_state, set_checkpoint, undo_checkin, write_english,
    write_state,
)

logger = logging.getLogger(__name__)
AuthDep = Callable[..., Awaitable[Any] | Any]

#: 专用线程池。默认执行器与后台任务(新闻抓取等)共用,四个领域会排在后面
#: 排队。这里隔开,免得互相拖累。
_EXECUTOR = ThreadPoolExecutor(max_workers=len(DOMAINS), thread_name_prefix="growth-plan")

#: 单个领域的硬上限。``ChatLLM.chat`` 的 timeout 形参会被 LangChain 的 config
#: 静默忽略(实测 timeout=1 的调用跑满 7 秒仍然成功返回),所以超时必须在这一层
#: 用 ``asyncio.wait_for`` 兜住,否则 provider 一挂就永远不返回。
DOMAIN_TIMEOUT_SECONDS = 120


class _Job:
    """正在生成的那份计划。

    四个领域实测要两分多钟。同步等待意味着首次使用盯着一个空转盘,所以改成
    后台生成、前端轮询,每排好一个领域就能看到进度。单用户应用,放内存即可;
    后端重启会丢失,重来一次就是了。
    """

    def __init__(self, total: int) -> None:
        self.total = total
        self.ready = 0
        #: 持有任务的强引用。只传给 ``create_task`` 而不保存,任务可能被垃圾回收,
        #: 生成就会在半途静默消失(CPython 文档明确警告过这一点)。
        self.task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict:
        return {"generating": True, "ready": self.ready, "total": self.total}


_job: Optional[_Job] = None


def _today() -> str:
    return date.today().isoformat()


def _require_state() -> dict:
    state = read_state()
    if state is None:
        raise HTTPException(status_code=404, detail="还没有计划,请先生成")
    return state


def _payload(state: dict) -> dict:
    today = _today()
    doc = read_english()
    return {
        "configured": True,
        "start_date": state.get("start_date"),
        "chronotype": state.get("chronotype"),
        "intake": state.get("intake"),
        "plan": state.get("plan"),
        "checkpoints": state.get("checkpoints") or {},
        "overview": {
            **build_overview(state, today, english_days(doc)),
            # 英语不走计划,目标直接来自测试的当日战绩。
            "english": english_today(doc, today),
        },
    }


class DomainIntakeRequest(BaseModel):
    level: str = Field(..., max_length=32)
    minutes: int


class PlanRequest(BaseModel):
    """全部字段都来自点选,没有自由文本。"""
    domains: dict[str, DomainIntakeRequest]
    chronotype: str = Field(..., max_length=16)


class CheckinRequest(BaseModel):
    domain: str = Field(..., max_length=16)


class DomainRequest(BaseModel):
    domain: str = Field(..., max_length=16)


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


class CheckpointRequest(BaseModel):
    domain: str = Field(..., max_length=16)
    which: str = Field(..., max_length=8)
    value: str = Field("", max_length=120)


def register_growth_routes(app: FastAPI, *, require_auth: AuthDep) -> None:
    router = APIRouter(prefix="/growth", tags=["growth"], dependencies=[Depends(require_auth)])

    @router.get("/options")
    async def options():
        """点选项由后端给出,避免前后端各存一份导致漂移。"""
        return {
            "days": PLAN_DAYS,
            "minutes": list(MINUTE_CHOICES),
            "chronotypes": [{"key": k, "label": v} for k, v in CHRONOTYPES],
            "domains": [
                {
                    "key": d,
                    "label": DOMAIN_LABELS[d],
                    "levels": [{"key": k, "label": v} for k, v in LEVELS[d]],
                }
                for d in DOMAINS
            ],
        }

    @router.get("/state")
    async def state():
        if _job is not None:
            return {"configured": False, **_job.to_dict()}
        saved = read_state()
        if saved is None:
            return {"configured": False}
        return _payload(saved)

    async def _one_domain(name: str, intake: Intake) -> dict:
        """生成一个领域;超时或失败都退回兜底计划,保证整份计划能完成。"""
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    _EXECUTOR, generate_domain_plan,
                    name, intake.domains[name], intake.chronotype,
                ),
                timeout=DOMAIN_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 - 含 asyncio.TimeoutError
            logger.warning("growth: %s 超时或失败,使用兜底计划:%s", name, exc)
            return fallback_plan(name, intake.domains[name].minutes)

    async def _run_job(intake: Intake, job: _Job) -> None:
        global _job
        try:
            names = list(intake.domains)
            plans: dict[str, dict] = {}
            for coro in asyncio.as_completed([
                _collect(name, intake) for name in names
            ]):
                name, plan = await coro
                plans[name] = plan
                job.ready += 1
            write_state(new_state(
                plan={name: plans[name] for name in names},
                intake={k: {"level": v.level, "minutes": v.minutes}
                        for k, v in intake.domains.items()},
                chronotype=intake.chronotype,
                today=_today(),
            ))
        except Exception:  # noqa: BLE001
            logger.exception("growth: 计划生成失败")
        finally:
            _job = None

    async def _collect(name: str, intake: Intake) -> tuple[str, dict]:
        return name, await _one_domain(name, intake)

    @router.post("/plan")
    async def create_plan(payload: PlanRequest):
        """开始生成一份新计划。立即返回,进度通过 /growth/state 轮询。"""
        global _job
        if _job is not None:
            return {"configured": False, **_job.to_dict()}
        try:
            intake = Intake(
                domains={k: DomainIntake(level=v.level, minutes=v.minutes)
                         for k, v in payload.domains.items()},
                chronotype=payload.chronotype,
            )
            intake.validate()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        job = _Job(total=len(intake.domains))
        _job = job
        job.task = asyncio.create_task(_run_job(intake, job))
        return {"configured": False, **job.to_dict()}

    @router.post("/checkin")
    async def checkin(payload: CheckinRequest):
        try:
            updated = apply_checkin(_require_state(), domain=payload.domain, today=_today())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _payload(write_state(updated))

    @router.post("/checkin/undo")
    async def undo(payload: DomainRequest):
        updated = undo_checkin(_require_state(), domain=payload.domain, today=_today())
        return _payload(write_state(updated))

    @router.post("/checkpoint")
    async def checkpoint(payload: CheckpointRequest):
        try:
            updated = set_checkpoint(
                _require_state(), domain=payload.domain,
                which=payload.which, value=payload.value,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _payload(write_state(updated))

    @router.post("/reset")
    async def reset():
        clear_state()
        return {"configured": False}

    # ── 英语句型 ──────────────────────────────────────────────────────────────

    def _english_payload(doc: dict) -> dict:
        today = _today()
        reviews = doc.get("reviews") or {}
        return {
            "today": today,
            "session": build_session(reviews, today),
            "stats": stats(reviews, today),
            "today_progress": english_today(doc, today),
            "daily_goal": DAILY_GOAL,
            "favorites": favorites(reviews),
            "fast_ms": FAST_MS,
            "groups": [{"key": k, "label": v} for k, v in GROUPS.items()],
            "levels": _levels(),
        }

    def _levels() -> list[dict]:
        return [{"key": k, "label": v, "total": LEVEL_TOTALS[k]} for k, v in ENGLISH_LEVELS.items()]

    @router.get("/english")
    async def english():
        """今天要练的条目 + 进度。整份 100 条清单由 /english/patterns 单独给。"""
        return _english_payload(read_english())

    @router.get("/english/patterns")
    async def english_patterns():
        reviews = read_english().get("reviews") or {}
        return {
            "groups": [{"key": k, "label": v} for k, v in GROUPS.items()],
            "levels": _levels(),
            "patterns": [
                {**p.to_dict(), "box": int((reviews.get(p.id) or {}).get("box", -1))}
                for p in PATTERNS
            ],
        }

    @router.post("/english/studied")
    async def english_studied(payload: StudiedRequest):
        """学习页看过一条。只记接触,不打分——打分是测验的事。"""
        doc = read_english()
        try:
            reviews = mark_studied(doc.get("reviews") or {}, payload.pattern_id, _today())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _english_payload(write_english({**doc, "reviews": reviews}))

    @router.post("/english/favorite")
    async def english_favorite(payload: FavoriteRequest):
        doc = read_english()
        try:
            reviews = set_favorite(doc.get("reviews") or {}, payload.pattern_id, payload.favorite)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _english_payload(write_english({**doc, "reviews": reviews}))

    @router.get("/english/quiz")
    async def english_quiz(count: int = Query(20, ge=1, le=100)):
        """抽一批两选一的题。"""
        doc = read_english()
        reviews = doc.get("reviews") or {}
        return {
            "questions": pick_quiz(reviews, _today(), count=count),
            "options_per_question": QUIZ_OPTIONS,
            "fast_ms": FAST_MS,
            "stats": stats(reviews, _today()),
            "today_progress": english_today(doc, _today()),
        }

    @router.post("/english/answer")
    async def english_answer(payload: AnswerRequest):
        """判一次作答并推进盒子。对错在服务端判,客户端报不了"我对了"。"""
        correct = payload.chosen_id == payload.pattern_id
        today = _today()
        try:
            doc = record_answer(read_english(), payload.pattern_id, correct,
                                payload.elapsed_ms, today)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        write_english(doc)
        return {
            "correct": correct,
            "grade": (doc["reviews"][payload.pattern_id] or {}).get("last_grade", ""),
            "stats": stats(doc["reviews"], today),
            "today_progress": english_today(doc, today),
        }

    @router.post("/english/reset")
    async def english_reset():
        clear_english()
        return _english_payload(empty_english())

    app.include_router(router)
