from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request

from .collector import AnalyticsCollector
from .models import AnalyticsEvent
from .rollup import AnalyticsRollup

logger = logging.getLogger(__name__)


class AnalyticsRuntime:
    def __init__(
        self,
        collector: AnalyticsCollector,
        rollup: AnalyticsRollup,
        *,
        poll_seconds: float = 1.0,
    ) -> None:
        self.collector = collector
        self.rollup = rollup
        self.poll_seconds = poll_seconds
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task = self.task
        self.task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.flush_once()

    async def flush_once(self) -> int:
        try:
            return await asyncio.to_thread(self.collector.flush, 100)
        except Exception as exc:
            logger.warning("analytics runtime flush failed with %s", type(exc).__name__)
            return 0

    async def _run(self) -> None:
        last_rollup = 0.0
        while True:
            await self.flush_once()
            now = time.monotonic()
            if now - last_rollup >= 3600:
                try:
                    await asyncio.to_thread(self.rollup.run_missing_days)
                    await asyncio.to_thread(self.rollup.store.prune)
                except Exception as exc:
                    logger.warning("analytics rollup failed with %s", type(exc).__name__)
                last_rollup = now
            await asyncio.sleep(self.poll_seconds)

    def observe_http(self, request: Request, status_code: int, duration_ms: int) -> None:
        if request.url.path == "/api/analytics/events" or request.url.path == "/health":
            return
        if request.url.path.startswith(("/assets/", "/static/")):
            return
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or request.url.path
        self.collector.submit(
            AnalyticsEvent(
                event_id=f"http-{uuid4()}",
                kind="system",
                occurred_at=datetime.now(timezone.utc),
                feature="http",
                action="request",
                outcome="success" if status_code < 500 else "failure",
                duration_ms=max(0, duration_ms),
                metadata={
                    "route": route_path,
                    "method": request.method,
                    "status_code": status_code,
                },
            )
        )

    def observe_provider(
        self,
        provider: str,
        market: str,
        status: str,
        duration_ms: int,
        observed_count: int,
        expected_count: int,
        data_freshness_ms: int | None,
        freshness_slo_ms: int,
        *,
        error_code: str | None = None,
    ) -> None:
        metadata = {
            "provider": provider,
            "market": market,
            "observed_count": max(0, observed_count),
            "expected_count": max(0, expected_count),
            "freshness_slo_ms": max(0, freshness_slo_ms),
        }
        if data_freshness_ms is not None:
            metadata["data_freshness_ms"] = max(0, data_freshness_ms)
        if error_code:
            metadata["error_code"] = error_code
        self.collector.submit(
            AnalyticsEvent(
                event_id=f"provider-{uuid4()}",
                kind="system",
                occurred_at=datetime.now(timezone.utc),
                feature="price_history",
                action="provider_fetch",
                outcome="success" if status == "success" else "failure",
                duration_ms=max(0, duration_ms),
                metadata=metadata,
            )
        )
