from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx


ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seedance-2-0-260128"


def _load_project_env() -> None:
    """Load the agent .env without overriding process-level configuration."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class SeedanceError(RuntimeError):
    """A user-facing Ark video generation error."""


class SeedanceClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        _load_project_env()
        self.api_key = (api_key or os.getenv("ARK_API_KEY", "")).strip()
        self.base_url = (base_url or os.getenv("ARK_BASE_URL", ARK_BASE_URL)).rstrip("/")
        self.model = (model or os.getenv("ARK_VIDEO_MODEL", DEFAULT_MODEL)).strip()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise SeedanceError("未配置 ARK_API_KEY，请先在 agent/.env 中配置豆包 Ark API Key。")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.is_success:
            return
        detail = response.text[:800]
        try:
            body = response.json()
            error = body.get("error", body) if isinstance(body, dict) else body
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("code") or error)
            else:
                detail = str(error)
        except ValueError:
            pass
        raise SeedanceError(f"Ark 视频接口请求失败（HTTP {response.status_code}）：{detail}")

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": payload["prompt"]}]
        for url in payload.get("image_urls", []):
            content.append({
                "type": "image_url",
                "image_url": {"url": url},
                "role": "reference_image",
            })
        if payload.get("reference_video_url"):
            content.append({
                "type": "video_url",
                "video_url": {"url": payload["reference_video_url"]},
                "role": "reference_video",
            })
        if payload.get("reference_audio_url"):
            content.append({
                "type": "audio_url",
                "audio_url": {"url": payload["reference_audio_url"]},
                "role": "reference_audio",
            })

        ark_payload = {
            "model": self.model,
            "content": content,
            "generate_audio": payload.get("generate_audio", True),
            "ratio": payload.get("ratio", "16:9"),
            "resolution": payload.get("resolution", "720p"),
            "duration": payload.get("duration", 5),
            "watermark": payload.get("watermark", False),
        }
        try:
            response = httpx.post(
                f"{self.base_url}/contents/generations/tasks",
                headers=self._headers(),
                json=ark_payload,
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        except httpx.TimeoutException as exc:
            raise SeedanceError("Ark 视频任务创建超时，请稍后重试。") from exc
        except httpx.HTTPError as exc:
            raise SeedanceError(f"无法连接 Ark 视频接口：{exc}") from exc
        self._raise_for_error(response)
        result = response.json()
        if not isinstance(result, dict) or not result.get("id"):
            raise SeedanceError("Ark 返回了无效的任务结果。")
        return result

    def get_task(self, task_id: str) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self.base_url}/contents/generations/tasks/{task_id}",
                headers=self._headers(),
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        except httpx.TimeoutException as exc:
            raise SeedanceError("查询视频生成进度超时，请稍后重试。") from exc
        except httpx.HTTPError as exc:
            raise SeedanceError(f"无法连接 Ark 视频接口：{exc}") from exc
        self._raise_for_error(response)
        result = response.json()
        if not isinstance(result, dict):
            raise SeedanceError("Ark 返回了无效的任务状态。")
        content = result.get("content")
        if isinstance(content, dict) and content.get("video_url"):
            result["video_url"] = content["video_url"]
        return result
