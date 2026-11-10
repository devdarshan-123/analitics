from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings

log = logging.getLogger("app.scheduler")

JOB_ID = "clarity_daily_sync"
_scheduler: BackgroundScheduler | None = None


def _trigger() -> CronTrigger:
    s = get_settings()
    return CronTrigger(hour=s.clarity_sync_hour, minute=s.clarity_sync_minute, timezone=s.zone)


def start_scheduler() -> None:
    """Run the Clarity sync daily (default 02:00 local). Run only ONE scheduler process per database."""
    global _scheduler
    from app.jobs.clarity_sync import run_scheduled

    if _scheduler is not None:
        return
    s = get_settings()
    _scheduler = BackgroundScheduler(timezone=s.zone)
    _scheduler.add_job(run_scheduled, _trigger(), id=JOB_ID, replace_existing=True, coalesce=True,
                       max_instances=1, misfire_grace_time=3 * 3600)
    _scheduler.start()
    log.info("Scheduler started; next Clarity sync at %s", next_run_time())


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_run_time() -> datetime | None:
    if _scheduler is not None:
        job = _scheduler.get_job(JOB_ID)
        return job.next_run_time if job else None
    s = get_settings()
    return _trigger().get_next_fire_time(None, datetime.now(s.zone))
