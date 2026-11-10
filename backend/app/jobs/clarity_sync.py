"""Daily Clarity sync for every enabled Clarity project. Run manually with:  python -m app.jobs.clarity_sync

Per project: a small fixed set of calls (max 6/run) so each project stays well under Clarity's
10 requests/project/day; raw + normalised data is stored under the project's GA4 property and the
run is idempotent per (property, snapshot date, dimension set). Projects are independent: one
failing, lacking a token, or hitting 429 never stops the others.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import ClarityProject, ClarityRawSnapshot, ClaritySyncRun
from app.schemas import ProjectSyncResult, SyncResult
from app.services.clarity import (
    ClarityAuthError,
    ClarityClient,
    ClarityError,
    ClarityFetcher,
    ClarityQuotaExceeded,
    dims_key,
    mark_exhausted,
    snapshot_exists,
    store_snapshot,
    try_reserve_call,
)
from app.services.clarity_projects import TokenUnavailable, all_projects, resolve_token

log = logging.getLogger("app.jobs.clarity_sync")

# (numOfDays, dimensions). Order matters: most valuable first, in case the quota runs out.
DAILY_CALLS: list[tuple[int, list[str]]] = [
    (1, []),
    (1, ["URL"]),
    (1, ["Device"]),
    (1, ["Source"]),
    (1, ["Country/Region"]),
]
BACKFILL_CALL: tuple[int, list[str]] = (3, [])

FetcherFactory = Callable[[ClarityProject], ClarityFetcher]

_lock = threading.Lock()


def get_fetcher(settings: Settings, project: ClarityProject) -> ClarityFetcher:
    """Raises TokenUnavailable when the project has no usable token."""
    if settings.mock_mode or project.token_source == "mock":
        from app.services.clarity_mock import MockClarityClient

        return MockClarityClient(settings.zone, project.ga_property_id)
    return ClarityClient(resolve_token(project, settings), settings.clarity_base_url)


def plan_calls(db: Session, property_id: str, max_calls: int) -> list[tuple[int, list[str]]]:
    first_run = db.execute(select(ClarityRawSnapshot.id).where(ClarityRawSnapshot.property_id == property_id)
                           .limit(1)).first() is None
    plan = ([BACKFILL_CALL] if first_run else []) + DAILY_CALLS
    return plan[:max_calls]


def _status(stored: int, errors: list[str]) -> str:
    if stored and not errors:
        return "success"
    if stored:
        return "partial"
    return "failed" if errors else "skipped"


def sync_project(db: Session, project: ClarityProject, fetcher: ClarityFetcher | None, settings: Settings,
                 trigger: str = "manual", today: date | None = None, now: datetime | None = None,
                 setup_error: str | None = None) -> ProjectSyncResult:
    """Sync one project. Records a ClaritySyncRun; never raises for Clarity/API problems."""
    today = today or datetime.now(settings.zone).date()
    # numOfDays=1 covers the last 24h; at 02:00 local that is essentially "yesterday".
    snapshot_date = today - timedelta(days=1)
    pid = project.ga_property_id
    run = ClaritySyncRun(trigger=trigger, status="running", property_id=pid, clarity_project_id=project.id)
    db.add(run)
    db.commit()

    calls = stored = 0
    skipped: list[str] = []
    errors: list[str] = []
    stop_reason = setup_error or ""

    if fetcher is not None and not setup_error:
        for num_days, dims in plan_calls(db, pid, settings.clarity_max_calls_per_run):
            label = f"{dims_key(dims) or 'totals'} ({num_days}d)"
            if snapshot_exists(db, pid, snapshot_date, dims, num_days):
                skipped.append(label)
                continue
            if not try_reserve_call(db, project.id, settings.clarity_safety_limit, now):
                stop_reason = (f"Quota guard: {settings.clarity_safety_limit} Clarity calls already used today (UTC) "
                               f"for this project")
                log.warning("Property %s: %s", pid, stop_reason)
                break
            calls += 1
            try:
                payload = fetcher.fetch(num_days, dims)
            except ClarityQuotaExceeded as e:
                mark_exhausted(db, project.id, settings.clarity_daily_limit, now)
                stop_reason = str(e)
                log.warning("Property %s: Clarity returned 429; marking this project's quota as exhausted", pid)
                break
            except ClarityAuthError as e:
                stop_reason = str(e)
                errors.append(f"{label}: {e}")
                break
            except ClarityError as e:
                errors.append(f"{label}: {e}")
                continue
            _, parsed = store_snapshot(db, pid, snapshot_date, dims, num_days, payload, project_id=project.id)
            db.commit()
            stored += 1
            log.info("Property %s: stored Clarity snapshot %s for %s: %d values (%d unknown metrics)", pid, label,
                     snapshot_date, len(parsed.values), len(parsed.unknown_metrics))

    if stop_reason and stop_reason not in errors and not any(stop_reason in e for e in errors):
        errors.append(stop_reason)
    status = _status(stored, errors)
    message = (f"Stored {stored} snapshot(s) for {snapshot_date} using {calls} API call(s)"
               + (f"; already had {len(skipped)}" if skipped else "")
               + (f"; {len(errors)} problem(s)" if errors else ""))

    run.status, run.calls_made, run.snapshots_stored = status, calls, stored
    run.message = message + ("\n" + "\n".join(errors) if errors else "")
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    log.info("Clarity sync property=%s project=%s: %s — %s", pid, project.id, status, message)
    return ProjectSyncResult(property_id=pid, project_id=project.id, label=project.label, status=status,
                             calls_made=calls, snapshots_stored=stored, skipped=skipped, errors=errors, message=message)


def run_sync(db: Session, settings: Settings, trigger: str = "manual", property_ids: set[str] | None = None,
             fetcher_factory: FetcherFactory | None = None, today: date | None = None,
             now: datetime | None = None) -> SyncResult:
    """Sync every enabled project (or just `property_ids`). Each project is isolated from the others."""
    if not _lock.acquire(blocking=False):
        return SyncResult(status="skipped", calls_made=0, snapshots_stored=0, skipped=[], errors=[],
                          message="A Clarity sync is already running", projects=[])
    try:
        factory = fetcher_factory or (lambda p: get_fetcher(settings, p))
        projects = [p for p in all_projects(db) if p.enabled and (property_ids is None or p.ga_property_id in property_ids)]
        results: list[ProjectSyncResult] = []
        for project in projects:
            try:
                try:
                    fetcher, setup_error = factory(project), None
                except TokenUnavailable as e:
                    fetcher, setup_error = None, str(e)
                results.append(sync_project(db, project, fetcher, settings, trigger, today, now, setup_error))
            except Exception as e:  # noqa: BLE001 — one project's crash must not stop the rest
                db.rollback()
                log.exception("Clarity sync crashed for property %s", project.ga_property_id)
                results.append(ProjectSyncResult(property_id=project.ga_property_id, project_id=project.id,
                                                 label=project.label, status="failed", calls_made=0, snapshots_stored=0,
                                                 skipped=[], errors=[f"Unexpected error: {type(e).__name__}"],
                                                 message="Sync crashed"))
        return aggregate(results)
    finally:
        _lock.release()


def aggregate(results: list[ProjectSyncResult]) -> SyncResult:
    if not results:
        return SyncResult(status="skipped", calls_made=0, snapshots_stored=0, skipped=[], errors=[],
                          message="No enabled Clarity projects to sync", projects=[])
    statuses = {r.status for r in results}
    if statuses <= {"success", "skipped"}:
        status = "success" if "success" in statuses else "skipped"
    elif statuses == {"failed"}:
        status = "failed"
    else:
        status = "partial"
    if len(results) == 1:
        message = results[0].message
    else:
        counts = ", ".join(f"{sum(r.status == s for r in results)} {s}" for s in ("success", "partial", "skipped", "failed")
                           if any(r.status == s for r in results))
        message = f"Synced {len(results)} Clarity projects: {counts}"
    return SyncResult(
        status=status,
        calls_made=sum(r.calls_made for r in results),
        snapshots_stored=sum(r.snapshots_stored for r in results),
        skipped=[s for r in results for s in r.skipped] if len(results) == 1 else [],
        errors=[e if len(results) == 1 else f"{r.property_id}: {e}" for r in results for e in r.errors],
        message=message,
        projects=results,
    )


def run_scheduled() -> None:
    """Entry point for APScheduler."""
    from app.db import SessionLocal

    settings = get_settings()
    with SessionLocal() as db:
        try:
            bootstrap(db, settings)
            run_sync(db, settings, trigger="scheduled")
        except Exception:
            log.exception("Scheduled Clarity sync crashed")


def bootstrap(db: Session, settings: Settings) -> None:
    """Seed env/mock projects and attach legacy single-property data to the default property."""
    from app.services.clarity_projects import adopt_unassigned_rows, seed_projects
    from app.services.properties import default_property_id

    default = default_property_id()
    seed_projects(db, settings, default)
    adopt_unassigned_rows(db, default)


def seed_mock_history(db: Session, settings: Settings, days: int = 29) -> int:
    """MOCK_MODE only: pre-fill history for each mock project up to the day before yesterday without
    touching the quota, so the first manual/scheduled sync still has yesterday's snapshots to fetch."""
    from app.services.clarity_mock import mock_payload

    yesterday = datetime.now(settings.zone).date() - timedelta(days=1)
    count = 0
    for project in all_projects(db):
        if project.token_source != "mock":
            continue
        pid = project.ga_property_id
        if db.execute(select(ClarityRawSnapshot.id).where(ClarityRawSnapshot.property_id == pid).limit(1)).first():
            continue
        for offset in range(days, 0, -1):
            day = yesterday - timedelta(days=offset)
            for num_days, dims in DAILY_CALLS:
                store_snapshot(db, pid, day, dims, num_days, mock_payload(day, dims, num_days, pid), project_id=project.id)
                count += 1
    db.commit()
    if count:
        log.info("MOCK_MODE: seeded %d Clarity snapshots", count)
    return count


def main() -> None:
    from app.db import SessionLocal, init_db
    from app.main import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    with SessionLocal() as db:
        bootstrap(db, settings)
        result = run_sync(db, settings, trigger="cli")
    print(json.dumps(result.model_dump(), indent=2, default=str))


if __name__ == "__main__":
    main()
