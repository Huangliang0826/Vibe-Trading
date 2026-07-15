from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Literal

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.video_generation import SeedanceClient, SeedanceError

AuthDep = Callable[..., Awaitable[Any] | Any]
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


class VideoGenerationCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=5000)
    image_urls: list[str] = Field(default_factory=list, max_length=4)
    reference_video_url: str | None = Field(default=None, max_length=4000)
    reference_audio_url: str | None = Field(default=None, max_length=4000)
    ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"] = "16:9"
    resolution: Literal["480p", "720p", "1080p"] = "720p"
    duration: int = Field(default=5, ge=4, le=12)
    generate_audio: bool = True
    watermark: bool = False

    @field_validator("image_urls")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        total = sum(len(value) for value in values)
        if total > 28_000_000:
            raise ValueError("参考图片总大小不能超过约 20 MB")
        for value in values:
            if not (value.startswith("https://") or value.startswith("data:image/")):
                raise ValueError("参考图片必须是 HTTPS 地址或已上传的图片")
        return values

    @field_validator("reference_video_url", "reference_audio_url")
    @classmethod
    def validate_media_url(cls, value: str | None) -> str | None:
        if value and not value.startswith("https://"):
            raise ValueError("参考视频和音频必须使用 HTTPS 地址")
        return value


def register_video_generation_routes(
    app: FastAPI,
    *,
    require_auth: AuthDep,
    client: SeedanceClient | None = None,
) -> None:
    seedance = client or SeedanceClient()
    router = APIRouter(prefix="/video-generation", dependencies=[Depends(require_auth)])

    def valid_task_id(task_id: str) -> str:
        if not TASK_ID_RE.fullmatch(task_id):
            raise HTTPException(status_code=400, detail="无效的视频任务 ID")
        return task_id

    @router.post("/tasks")
    async def create_task(payload: VideoGenerationCreate) -> dict[str, Any]:
        try:
            return seedance.create_task(payload.model_dump())
        except SeedanceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str) -> dict[str, Any]:
        try:
            return seedance.get_task(valid_task_id(task_id))
        except SeedanceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/download")
    async def download_task(task_id: str) -> StreamingResponse:
        task_id = valid_task_id(task_id)
        try:
            task = seedance.get_task(task_id)
        except SeedanceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        video_url = task.get("video_url") or (task.get("content") or {}).get("video_url")
        if task.get("status") != "succeeded" or not video_url:
            raise HTTPException(status_code=409, detail="视频尚未生成完成")

        async def stream_video():
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=180.0) as http:
                    async with http.stream("GET", video_url) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            yield chunk
            except httpx.HTTPError as exc:
                raise SeedanceError(f"下载生成视频失败：{exc}") from exc

        return StreamingResponse(
            stream_video(),
            media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="seedance-{task_id}.mp4"'},
        )

    app.include_router(router)
