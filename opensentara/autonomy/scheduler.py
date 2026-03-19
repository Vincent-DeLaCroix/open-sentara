"""Scheduler — manages autonomous behavior intervals."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger(__name__)


def parse_interval(interval_str: str) -> dict:
    """Parse interval string like '4h', '30m', '24h' into kwargs for IntervalTrigger."""
    match = re.match(r"^(\d+)(m|h|d)$", interval_str.strip())
    if not match:
        raise ValueError(f"Invalid interval format: {interval_str}")
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return {"minutes": value}
    elif unit == "h":
        return {"hours": value}
    elif unit == "d":
        return {"days": value}
    return {"hours": 4}


class SentaraScheduler:
    """Manages the autonomous behavior loop."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}  # name -> job_id
        self._running: set[str] = set()
        self.paused = False

    def add_job(self, name: str, func, interval_str: str) -> None:
        """Add a scheduled job."""
        kwargs = parse_interval(interval_str)

        async def wrapped():
            if name in self._running:
                log.warning(f"Skipping {name}: previous run still active")
                return
            self._running.add(name)
            try:
                log.info(f"Running scheduled job: {name}")
                await func()
            except Exception as e:
                log.error(f"Scheduled job {name} failed: {e}", exc_info=True)
            finally:
                self._running.discard(name)

        job = self.scheduler.add_job(
            wrapped,
            trigger=IntervalTrigger(**kwargs),
            id=name,
            name=name,
            replace_existing=True,
        )
        self._jobs[name] = job.id
        log.info(f"Scheduled {name} every {interval_str}")

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            log.info("Scheduler started")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            log.info("Scheduler stopped")

    def pause(self) -> None:
        """Pause all scheduled jobs (she sleeps)."""
        if not self.paused:
            self.scheduler.pause()
            self.paused = True
            log.info("Scheduler paused — Sentara is sleeping")

    def resume(self) -> None:
        """Resume all scheduled jobs (she wakes up)."""
        if self.paused:
            self.scheduler.resume()
            self.paused = False
            log.info("Scheduler resumed — Sentara is awake")

    def get_status(self) -> list[dict]:
        """Get status of all scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "running": job.name in self._running,
            })
        return jobs

    async def trigger(self, name: str) -> bool:
        """Manually trigger a job by name."""
        job = self.scheduler.get_job(name)
        if not job:
            return False
        # Run it now in background
        asyncio.create_task(job.func())
        return True
