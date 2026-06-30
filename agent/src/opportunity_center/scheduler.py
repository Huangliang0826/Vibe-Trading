"""Post-close scheduler for HK and US opportunity snapshots."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from src.opportunity_center.models import Market, RefreshJob
from src.opportunity_center.service import OpportunityService

MARKET_ZONES = {"hk": ZoneInfo("Asia/Hong_Kong"), "us": ZoneInfo("America/New_York")}
CLOSE_CUTOFF = time(16, 15)
logger = logging.getLogger(__name__)


def due_market_dates(now: datetime) -> dict[Market, date]:
    aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    due: dict[Market, date] = {}
    for market, zone in MARKET_ZONES.items():
        local = aware.astimezone(zone)
        if local.weekday() < 5 and local.time() >= CLOSE_CUTOFF:
            due[market] = local.date()
        elif local.weekday() >= 5:
            day = local.date()
            while day.weekday() >= 5:
                day -= timedelta(days=1)
            due[market] = day
    return due


class OpportunityScheduler:
    def __init__(self, service: OpportunityService, poll_seconds: int = 300) -> None:
        self.service = service
        self.poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_once(self, now: datetime | None = None) -> RefreshJob | None:
        due = due_market_dates(now or datetime.now(timezone.utc))
        pending = {
            market: market_date.isoformat()
            for market, market_date in due.items()
            if not self.service.store.has_market_refresh(market, market_date.isoformat())
        }
        if not pending:
            return None
        job = self.service.start_refresh(list(pending), "scheduled", market_dates=pending)
        await self.service.run_job(job.job_id)
        return self.service.store.get_job(job.job_id)

    async def _run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as exc:
                logger.warning("opportunity scheduler refresh failed: %s", exc)
            await asyncio.sleep(self.poll_seconds)
