from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.config import get_settings
from app.db import get_db
from app.deps import linked_clarity_project, selected_property
from app.jobs.scheduler import next_run_time
from app.models import ClarityProject, ClaritySyncRun
from app.schemas import (
    ClarityBreakdown,
    ClarityFrustration,
    ClarityOverview,
    ClarityPages,
    ClarityProjectOut,
    ClarityStatus,
    SyncRunInfo,
)
from app.services import clarity_queries as q
from app.services.clarity import get_usage, utc_today
from app.services.clarity_projects import has_token, project_for_property
from app.utils.dates import DateRange, date_range_params

router = APIRouter(prefix="/api/clarity", tags=["clarity"], dependencies=[Depends(require_auth)])

# All endpoints read stored snapshots for the selected property only — the Clarity API is called by the sync job.
# Properties without a linked Clarity project get 404 clarity_not_linked (status reports linked=false instead).


@router.get("/overview", response_model=ClarityOverview)
def overview(r: DateRange = Depends(date_range_params), project: ClarityProject = Depends(linked_clarity_project),
             db: Session = Depends(get_db)) -> ClarityOverview:
    return q.overview(db, project.ga_property_id, r)


@router.get("/frustration", response_model=ClarityFrustration)
def frustration(r: DateRange = Depends(date_range_params), project: ClarityProject = Depends(linked_clarity_project),
                db: Session = Depends(get_db)) -> ClarityFrustration:
    return q.frustration(db, project.ga_property_id, r)


@router.get("/pages", response_model=ClarityPages)
def pages(r: DateRange = Depends(date_range_params), project: ClarityProject = Depends(linked_clarity_project),
          db: Session = Depends(get_db)) -> ClarityPages:
    return q.pages_response(db, project.ga_property_id, r)


@router.get("/breakdown", response_model=ClarityBreakdown)
def breakdown(dimension: Literal["Device", "Source", "Country"] = Query(...),
              project: ClarityProject = Depends(linked_clarity_project), db: Session = Depends(get_db)) -> ClarityBreakdown:
    return q.breakdown(db, project.ga_property_id, dimension)


def last_run_for(db: Session, property_id: str) -> ClaritySyncRun | None:
    return db.execute(select(ClaritySyncRun).where(ClaritySyncRun.property_id == property_id)
                      .order_by(ClaritySyncRun.started_at.desc()).limit(1)).scalar_one_or_none()


def project_out(db: Session, project: ClarityProject) -> ClarityProjectOut:
    s = get_settings()
    usage = get_usage(db, project.id)
    last = last_run_for(db, project.ga_property_id)
    return ClarityProjectOut(
        id=project.id, ga_property_id=project.ga_property_id, label=project.label, enabled=project.enabled,
        token_source=project.token_source,  # type: ignore[arg-type]
        has_token=has_token(project, s), created_at=project.created_at,
        calls_used_today=usage.calls if usage else 0, quota_exhausted=bool(usage and usage.exhausted),
        last_run=SyncRunInfo.model_validate(last, from_attributes=True) if last else None,
    )


def build_status(db: Session, property_id: str) -> ClarityStatus:
    s = get_settings()
    project = project_for_property(db, property_id)
    usage = get_usage(db, project.id) if project else None
    used = usage.calls if usage else 0
    exhausted = bool(usage and usage.exhausted)
    last_run = last_run_for(db, property_id)
    last_ok = db.execute(select(ClaritySyncRun.finished_at).where(
        ClaritySyncRun.property_id == property_id, ClaritySyncRun.status.in_(["success", "partial"]))
        .order_by(ClaritySyncRun.started_at.desc()).limit(1)).scalar()
    remaining = max(0, s.clarity_safety_limit - used)
    token_ok = bool(project) and has_token(project, s)
    return ClarityStatus(
        property_id=property_id,
        linked=project is not None,
        project=project_out(db, project) if project else None,
        mock_mode=s.mock_mode,
        token_configured=token_ok,
        last_successful_sync=last_ok,
        last_run=SyncRunInfo.model_validate(last_run, from_attributes=True) if last_run else None,
        calls_used_today=used,
        daily_limit=s.clarity_daily_limit,
        safety_limit=s.clarity_safety_limit,
        calls_remaining=0 if exhausted else remaining,
        # "Sync now" is offered only for an enabled project with a token while the quota guard leaves headroom.
        sync_available=bool(project and project.enabled and token_ok) and not exhausted and remaining >= 2,
        quota_exhausted=exhausted,
        next_scheduled_run=next_run_time(),
        scheduler_enabled=s.enable_scheduler,
        history_start=q.history_start(db, property_id),
        latest_snapshot=q.latest_snapshot(db, property_id),
        utc_day=utc_today(),
    )


@router.get("/status", response_model=ClarityStatus)
def status(property_id: str = Depends(selected_property), db: Session = Depends(get_db)) -> ClarityStatus:
    return build_status(db, property_id)
