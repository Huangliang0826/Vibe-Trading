"""量化学习 · AI 动态出题路由。

基于一条知识卡片的内容,调用 DeepSeek 官方 API(deepseek-v4-pro)现场生成一道
选择/判断/情景题。与全局 agent 使用的 provider 解耦:无论 LANGCHAIN_PROVIDER
设成什么,这里都直接读取 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL 打到 DeepSeek 官方端点。

前端在 AI 出题失败(未配置 key、网络错误、返回非法 JSON)时会自动回退到内置题库,
因此本路由的失败以 503 明确表达,不影响复习功能可用性。
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from typing import Any, Awaitable, Callable

import anyio
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.config.paths import get_runtime_root

logger = logging.getLogger(__name__)
AuthDep = Callable[..., Awaitable[Any] | Any]

# 单用户共享的学习状态(进度 + AI 扩充卡片),用于手机 / 网页跨设备同步
_STATE_FILENAME = "learning_state.json"
_MAX_STATE_BYTES = 8 * 1024 * 1024  # 8MB 上限,防止异常膨胀


def _state_path() -> "os.PathLike[str]":
    return get_runtime_root() / _STATE_FILENAME

QUIZ_MODEL_ENV = "LEARNING_QUIZ_MODEL"
DEFAULT_QUIZ_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

_ALLOWED_TYPES = {"choice", "judge", "scenario"}

_SYSTEM_PROMPT = (
    "你是一位资深的量化交易与投资教育出题老师。请根据给定的知识点,出一道中文测验题,"
    "用于检验学习者是否真正理解(而非死记)。要求:\n"
    "1. 题目类型从 choice(选择题)、judge(判断改错题)、scenario(情景应用题)中择一,优先出"
    "能考察『理解与应用』的情景题或判断题;\n"
    "2. 恰好 4 个选项,只有 1 个正确;干扰项要有迷惑性(常见误区),但不能有歧义或多个正确;\n"
    "3. 解析要点明为什么对、为什么其它错,一两句话即可;\n"
    "4. 题目必须紧扣给定知识点,不得脱离;语言简洁专业,避免空话;\n"
    "5. 解析中指代选项时,请用该选项的核心内容或关键词来指代,"
    "不要使用字母(A/B/C/D)或『选项一/二』等位置序号——因为选项顺序在展示时会被随机打乱;\n"
    "6. 只输出一个 JSON 对象,字段:type、question、options(字符串数组,长度4)、"
    "answer(正确选项的下标,0-3 的整数)、explanation。不要输出任何多余文字或 markdown。"
)


_CARDS_SYSTEM_PROMPT = (
    "你是一位资深的量化交易与投资教育内容作者。请为给定主题续写若干条『知识卡片』,"
    "风格与深度对标一本优秀的交易科普书:既有干货又有趣味,能讲清『为什么』,常引用真实市场"
    "案例或反直觉现象。每条卡片必须满足:\n"
    "1. type 从 concept(概念)、story(真实市场故事)、pitfall(常见陷阱)中择一,三类穿插,"
    "不要全是概念;\n"
    "2. difficulty 为 1/2/3(入门/进阶/高阶)整数;\n"
    "3. title:一句话记忆点,精炼有钩子;core:2-4 句把核心与『为什么』讲透;\n"
    "4. example:一个具体案例或真实市场故事(如著名事件、经典研究、反直觉现象);\n"
    "5. pitfall:一句『很多人以为…其实…』式的常见误区;\n"
    "6. 每条配一道 quiz(字段 type: choice/judge/scenario、question、options 长度4、"
    "answer 为正确项下标 0-3、explanation),优先情景题/判断题;解析中指代选项请用其内容或"
    "关键词而非字母序号(选项展示时会被打乱);\n"
    "7. 内容必须紧扣主题,彼此不重复,也不得与『已有知识点』列表雷同;语言简洁专业;\n"
    "8. 只输出一个 JSON 对象:{\"cards\": [ ... ]},数组每项含上述字段。不要输出多余文字或 markdown。"
)


class GenerateCardsRequest(BaseModel):
    """AI 扩充知识点请求:为某主题续写若干条卡片。"""

    topic_id: str = Field(..., max_length=40)
    topic_title: str = Field(..., max_length=100)
    topic_subtitle: str = Field(default="", max_length=200)
    existing_titles: list[str] = Field(default_factory=list)
    count: int = Field(default=10, ge=1, le=10)


class GeneratedCard(BaseModel):
    """AI 生成的一条知识卡片(不含 id/topicId,由前端补齐)。"""

    type: str
    difficulty: int
    title: str
    core: str
    example: str | None = None
    pitfall: str | None = None
    quiz: GeneratedQuiz


class GenerateCardsResponse(BaseModel):
    cards: list[GeneratedCard]


class LearningState(BaseModel):
    """跨设备同步的学习状态载荷(内容对后端透明,仅做存取)。"""

    progress: Any | None = None
    extra: Any | None = None


def _read_state() -> LearningState:
    from pathlib import Path

    path = Path(_state_path())
    if not path.exists():
        return LearningState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LearningState(progress=data.get("progress"), extra=data.get("extra"))
    except Exception:  # noqa: BLE001 — 损坏文件回退为空,不影响本地使用
        logger.warning("learning_state.json unreadable; returning empty")
        return LearningState()


def _write_state(state: LearningState) -> None:
    from pathlib import Path

    payload = json.dumps(state.model_dump(), ensure_ascii=False)
    if len(payload.encode("utf-8")) > _MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail="学习状态过大")
    path = Path(_state_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)  # 原子替换,避免并发写坏文件


class GenerateQuizRequest(BaseModel):
    """AI 出题请求:承载一条知识卡片的内容。"""

    topic_title: str = Field(..., max_length=100)
    title: str = Field(..., max_length=200)
    core: str = Field(..., max_length=4000)
    example: str | None = Field(default=None, max_length=4000)
    pitfall: str | None = Field(default=None, max_length=4000)
    # 已在题库中出现过的问法,提示模型换个角度考,避免雷同
    avoid_question: str | None = Field(default=None, max_length=1000)


class QuizBatchItem(BaseModel):
    """批量出题里的一条卡片(id 用于把生成结果对应回去)。"""

    id: str = Field(..., max_length=80)
    topic_title: str = Field(..., max_length=100)
    title: str = Field(..., max_length=200)
    core: str = Field(..., max_length=4000)
    example: str | None = Field(default=None, max_length=4000)
    pitfall: str | None = Field(default=None, max_length=4000)


class GenerateQuizBatchRequest(BaseModel):
    items: list[QuizBatchItem] = Field(..., max_length=12)


class QuizBatchResult(BaseModel):
    id: str
    quiz: GeneratedQuiz


class GenerateQuizBatchResponse(BaseModel):
    results: list[QuizBatchResult]


class GeneratedQuiz(BaseModel):
    """AI 生成的题目(结构与前端题库题一致)。"""

    type: str
    question: str
    options: list[str]
    answer: int
    explanation: str
    ai_generated: bool = True


def _build_user_prompt(req: GenerateQuizRequest) -> str:
    parts = [
        f"【主题】{req.topic_title}",
        f"【知识点标题】{req.title}",
        f"【核心讲解】{req.core}",
    ]
    if req.example:
        parts.append(f"【案例】{req.example}")
    if req.pitfall:
        parts.append(f"【常见误区】{req.pitfall}")
    if req.avoid_question:
        parts.append(f"【请勿与此题雷同,换个角度考】{req.avoid_question}")
    parts.append("请据此出一道 JSON 格式的测验题。")
    return "\n".join(parts)


def _extract_quiz_json(text: str) -> dict[str, Any]:
    """从模型输出中提取 JSON 对象,容忍 ```json 代码块或前后多余文字。"""
    if not text or not text.strip():
        raise ValueError("empty model output")
    cleaned = text.strip()
    # 去掉 ```json ... ``` 围栏
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 退而求其次:抓取第一个 { 到最后一个 } 之间的内容
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ValueError("no JSON object found in model output")


def _validate_and_shuffle(
    raw: dict[str, Any], rng: random.Random | None = None
) -> GeneratedQuiz:
    """校验字段合法性,并打乱选项顺序(消除正确项的位置偏置)。"""
    rng = rng or random.Random()
    qtype = str(raw.get("type", "choice")).strip().lower()
    if qtype not in _ALLOWED_TYPES:
        qtype = "choice"
    question = str(raw.get("question", "")).strip()
    options = raw.get("options")
    answer = raw.get("answer")
    explanation = str(raw.get("explanation", "")).strip()

    if not question or not explanation:
        raise ValueError("missing question or explanation")
    if not isinstance(options, list) or not (2 <= len(options) <= 6):
        raise ValueError("options must be a list of 2-6 items")
    options = [str(o).strip() for o in options if str(o).strip()]
    if len(options) < 2:
        raise ValueError("not enough non-empty options")
    if not isinstance(answer, int) or not (0 <= answer < len(options)):
        raise ValueError("answer index out of range")

    # 打乱选项,重算正确下标
    order = list(range(len(options)))
    rng.shuffle(order)
    shuffled = [options[i] for i in order]
    new_answer = order.index(answer)

    return GeneratedQuiz(
        type=qtype,
        question=question,
        options=shuffled,
        answer=new_answer,
        explanation=explanation,
    )


def _call_deepseek(
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.8,
    timeout: int | None = None,
    max_tokens: int | None = None,
) -> str:
    """直连 DeepSeek 官方 API 取一次补全,返回文本内容。

    与全局 provider 解耦:直接读取 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL。
    DeepSeek 兼容 OpenAI 接口,故复用 langchain_openai.ChatOpenAI + JSON 模式。
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="未配置 DEEPSEEK_API_KEY,无法使用 AI 功能")
    base_url = (
        os.getenv("DEEPSEEK_BASE_URL", "").strip()
        or os.getenv("OPENAI_BASE_URL", "").strip()
        or DEFAULT_DEEPSEEK_BASE_URL
    )
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - dependency always present in app
        raise HTTPException(status_code=503, detail="AI 功能依赖未安装") from exc

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout or int(os.getenv("LEARNING_QUIZ_TIMEOUT", "45")),
        max_retries=1,
        max_tokens=max_tokens,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    message = llm.invoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    content = getattr(message, "content", "")
    if isinstance(content, list):  # some providers return content parts
        content = "".join(str(p) for p in content)
    return str(content)


def _generate_quiz(req: GenerateQuizRequest) -> GeneratedQuiz:
    """完整的 AI 出题流程:构造提示 → 调用模型 → 解析 → 校验 → 打乱。"""
    model = os.getenv(QUIZ_MODEL_ENV, DEFAULT_QUIZ_MODEL).strip() or DEFAULT_QUIZ_MODEL
    raw_text = _call_deepseek(model, _SYSTEM_PROMPT, _build_user_prompt(req))
    parsed = _extract_quiz_json(raw_text)
    return _validate_and_shuffle(parsed)


_BATCH_SYSTEM_PROMPT = (
    "你是一位资深的量化交易与投资教育出题老师。下面给出若干个知识点,请为每个知识点各出"
    "一道中文测验题,检验是否真正理解而非死记。要求:\n"
    "1. 每题类型从 choice / judge / scenario 中择一,优先情景题、判断题;\n"
    "2. 恰好 4 个选项,只有 1 个正确,干扰项有迷惑性但无歧义;\n"
    "3. 解析点明为什么对、为什么其它错;指代选项时用其内容或关键词,不要用字母序号"
    "(选项展示时会被打乱);\n"
    "4. 紧扣对应知识点,题目之间不重复;\n"
    "5. 只输出一个 JSON 对象:{\"items\": [{\"id\": <原样返回该知识点的 id>, \"type\":..., "
    "\"question\":..., \"options\":[4个], \"answer\": <0-3>, \"explanation\":...}, ...]},"
    "不要输出多余文字或 markdown。"
)


def _build_batch_prompt(items: list[QuizBatchItem]) -> str:
    blocks = []
    for it in items:
        parts = [f"id: {it.id}", f"主题: {it.topic_title}", f"知识点: {it.title}", f"讲解: {it.core}"]
        if it.example:
            parts.append(f"案例: {it.example}")
        if it.pitfall:
            parts.append(f"误区: {it.pitfall}")
        blocks.append("\n".join(parts))
    return (
        "请为以下 " + str(len(items)) + " 个知识点各出一道题(每题带回对应的 id):\n\n"
        + "\n\n---\n\n".join(blocks)
    )


def _generate_quiz_batch(req: GenerateQuizBatchRequest) -> list[QuizBatchResult]:
    """一次调用生成整组题目,逐条校验后按 id 对应返回;非法项跳过。"""
    if not req.items:
        return []
    model = os.getenv(QUIZ_MODEL_ENV, DEFAULT_QUIZ_MODEL).strip() or DEFAULT_QUIZ_MODEL
    raw_text = _call_deepseek(
        model,
        _BATCH_SYSTEM_PROMPT,
        _build_batch_prompt(req.items),
        temperature=0.8,
        timeout=int(os.getenv("LEARNING_BATCH_TIMEOUT", "90")),
        max_tokens=6000,
    )
    obj = _extract_quiz_json(raw_text)
    items = obj.get("items") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        raise ValueError("no items array in model output")

    valid_ids = {it.id for it in req.items}
    rng = random.Random()
    results: list[QuizBatchResult] = []
    seen: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("id", "")).strip()
        if cid not in valid_ids or cid in seen:
            continue
        try:
            quiz = _validate_and_shuffle(entry, rng)
        except (ValueError, TypeError):
            continue
        seen.add(cid)
        results.append(QuizBatchResult(id=cid, quiz=quiz))
    return results


_CARD_TYPES = {"concept", "story", "pitfall"}


def _build_cards_prompt(req: GenerateCardsRequest) -> str:
    parts = [
        f"【主题】{req.topic_title}",
    ]
    if req.topic_subtitle:
        parts.append(f"【主题简介】{req.topic_subtitle}")
    # 只发最近的一部分已有标题,避免提示过长
    titles = [t.strip() for t in req.existing_titles if t.strip()][-40:]
    if titles:
        parts.append("【已有知识点(请勿重复,换新角度)】\n" + "\n".join(f"- {t}" for t in titles))
    parts.append(f"请续写 {req.count} 条全新的知识卡片,输出 {{\"cards\": [...]}} 的 JSON。")
    return "\n".join(parts)


def _validate_card(
    raw: dict[str, Any], existing_lower: set[str], rng: random.Random
) -> GeneratedCard:
    ctype = str(raw.get("type", "concept")).strip().lower()
    if ctype not in _CARD_TYPES:
        ctype = "concept"
    try:
        difficulty = int(raw.get("difficulty", 2))
    except (TypeError, ValueError):
        difficulty = 2
    if difficulty not in (1, 2, 3):
        difficulty = 2
    title = str(raw.get("title", "")).strip()
    core = str(raw.get("core", "")).strip()
    if not title or not core:
        raise ValueError("missing title or core")
    if title.lower() in existing_lower:
        raise ValueError("duplicate title")
    example = str(raw.get("example", "")).strip() or None
    pitfall = str(raw.get("pitfall", "")).strip() or None
    quiz = _validate_and_shuffle(raw.get("quiz") or {}, rng)
    return GeneratedCard(
        type=ctype,
        difficulty=difficulty,
        title=title,
        core=core,
        example=example,
        pitfall=pitfall,
        quiz=quiz,
    )


def _generate_cards(req: GenerateCardsRequest) -> list[GeneratedCard]:
    """AI 扩充知识点:一次生成多条卡片,逐条校验,丢弃非法/重复项。"""
    model = os.getenv(QUIZ_MODEL_ENV, DEFAULT_QUIZ_MODEL).strip() or DEFAULT_QUIZ_MODEL
    raw_text = _call_deepseek(
        model,
        _CARDS_SYSTEM_PROMPT,
        _build_cards_prompt(req),
        temperature=0.9,
        timeout=int(os.getenv("LEARNING_CARDS_TIMEOUT", "120")),
        max_tokens=8000,
    )
    obj = _extract_quiz_json(raw_text)
    items = obj.get("cards") if isinstance(obj, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("no cards array in model output")

    existing_lower = {t.strip().lower() for t in req.existing_titles if t.strip()}
    rng = random.Random()
    cards: list[GeneratedCard] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            card = _validate_card(item, existing_lower, rng)
        except (ValueError, TypeError):
            continue  # 跳过单条问题,尽量返回可用的其余卡片
        existing_lower.add(card.title.lower())  # 批内去重
        cards.append(card)
        if len(cards) >= req.count:
            break
    if not cards:
        raise ValueError("no valid cards produced")
    return cards


def register_learning_routes(app: FastAPI, *, require_auth: AuthDep) -> None:
    router = APIRouter(prefix="/learning", dependencies=[Depends(require_auth)])

    @router.post("/generate-quiz", response_model=GeneratedQuiz)
    async def generate_quiz(req: GenerateQuizRequest) -> GeneratedQuiz:
        try:
            return await anyio.to_thread.run_sync(_generate_quiz, req)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — 前端会回退到内置题库
            logger.warning("AI quiz generation failed: %s", exc)
            raise HTTPException(status_code=503, detail="AI 出题暂时不可用,已切换到题库") from exc

    @router.post("/generate-quiz-batch", response_model=GenerateQuizBatchResponse)
    async def generate_quiz_batch(req: GenerateQuizBatchRequest) -> GenerateQuizBatchResponse:
        try:
            results = await anyio.to_thread.run_sync(_generate_quiz_batch, req)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — 前端回退到题库
            logger.warning("AI quiz batch generation failed: %s", exc)
            raise HTTPException(status_code=503, detail="AI 批量出题暂时不可用") from exc
        return GenerateQuizBatchResponse(results=results)

    @router.post("/generate-cards", response_model=GenerateCardsResponse)
    async def generate_cards(req: GenerateCardsRequest) -> GenerateCardsResponse:
        try:
            cards = await anyio.to_thread.run_sync(_generate_cards, req)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI card generation failed: %s", exc)
            raise HTTPException(status_code=503, detail="AI 扩充知识点暂时不可用,请稍后再试") from exc
        return GenerateCardsResponse(cards=cards)

    @router.get("/state", response_model=LearningState)
    def get_state() -> LearningState:
        return _read_state()

    @router.put("/state", response_model=LearningState)
    def put_state(state: LearningState) -> LearningState:
        _write_state(state)
        return state

    app.include_router(router)
