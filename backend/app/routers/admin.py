from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.config import get_settings
from app.db import get_db
from app.deps import selected_property
from app.errors import AppError
from app.jobs.clarity_sync import get_fetcher, run_sync
from app.models import ClarityProject
from app.routers.clarity import build_status, project_out
from app.schemas import ClarityProjectIn, ClarityProjectOut, ClarityProjectPatch, ConnectionTest, SyncResult
from app.services.clarity import ClarityError, parse_live_insights, try_reserve_call
from app.services.clarity_projects import TokenUnavailable, all_projects, encrypt_token, project_for_property
from app.services.ga import get_ga_service
from app.services.properties import resolve_property_id

log = logging.getLogger("app.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------- sync
@router.post("/clarity/sync", response_model=SyncResult)
def clarity_sync(all_projects_: bool = Query(False, alias="all", description="Sync every enabled project"),
                 propertyId: str | None = Query(None, pattern=r"^\d{1,20}$"),  # noqa: N803
                 db: Session = Depends(get_db)) -> SyncResult:
    settings = get_settings()
    if all_projects_:
        return run_sync(db, settings, trigger="manual")
    pid = resolve_property_id(propertyId)
    project = project_for_property(db, pid)
    if project is None:
        raise AppError(404, "clarity_not_linked", f"No Clarity project is linked to GA4 property {pid}.",
                       hint="Link one in Settings → Clarity projects.")
    if not project.enabled:
        raise AppError(400, "clarity_project_disabled", "This Clarity project is disabled.", hint="Enable it in Settings first.")
    return run_sync(db, settings, trigger="manual", property_ids={pid})


# ---------------------------------------------------------------- connection tests
@router.post("/test/ga", response_model=ConnectionTest)
def test_ga(property_id: str = Depends(selected_property)) -> ConnectionTest:
    try:
        totals = get_ga_service(property_id).test_connection()
    except AppError as e:
        return ConnectionTest(source="ga", ok=False, message=e.message, details={"code": e.code, "hint": e.hint})
    return ConnectionTest(source="ga", ok=True, message=f"Connected to GA4 property {property_id} — last 2 days returned data.",
                          details=totals)


@router.post("/test/clarity", response_model=ConnectionTest)
def test_clarity(live: bool = Query(False, description="Make a real API call (uses 1 of the project's 10 daily calls)"),
                 property_id: str = Depends(selected_property), db: Session = Depends(get_db)) -> ConnectionTest:
    settings = get_settings()
    status = build_status(db, property_id)
    details = {"calls_used_today": status.calls_used_today, "token_configured": status.token_configured,
               "last_run_status": status.last_run.status if status.last_run else None}
    project = project_for_property(db, property_id)
    if project is None:
        return ConnectionTest(source="clarity", ok=False, message="No Clarity project is linked to this property.",
                              details=details)
    if not status.token_configured:
        return ConnectionTest(source="clarity", ok=False, message="This Clarity project has no usable API token.",
                              details=details)
    if not live:
        ok = status.last_run is None or status.last_run.status in ("success", "partial", "skipped")
        msg = ("Token configured. " + (f"Last sync: {status.last_run.status}." if status.last_run else "No sync has run yet.")
               + " Run a live test to verify the token (uses 1 API call).")
        return ConnectionTest(source="clarity", ok=ok, message=msg, details=details)
    try:
        fetcher = get_fetcher(settings, project)
    except TokenUnavailable as e:
        return ConnectionTest(source="clarity", ok=False, message=str(e), details=details)
    if not try_reserve_call(db, project.id, settings.clarity_safety_limit):
        return ConnectionTest(source="clarity", ok=False, message="Quota guard: no Clarity calls left today for this project.",
                              details=details)
    try:
        payload = fetcher.fetch(1, [])
    except ClarityError as e:
        return ConnectionTest(source="clarity", ok=False, message=str(e), details=details)
    parsed = parse_live_insights(payload)
    details.update(calls_used_today=status.calls_used_today + 1, metrics_returned=len({v.metric_name for v in parsed.values}))
    return ConnectionTest(source="clarity", ok=True, message="Clarity token works.", details=details)


# ---------------------------------------------------------------- Clarity project mapping
@router.get("/clarity/projects", response_model=list[ClarityProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[ClarityProjectOut]:
    return [project_out(db, p) for p in all_projects(db)]


def _get_project(db: Session, project_id: int) -> ClarityProject:
    project = db.get(ClarityProject, project_id)
    if project is None:
        raise AppError(404, "clarity_project_not_found", "Clarity project not found.")
    return project


def _clean_token(token: str | None) -> str | None:
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


@router.post("/clarity/projects", response_model=ClarityProjectOut)
def upsert_project(body: ClarityProjectIn, db: Session = Depends(get_db)) -> ClarityProjectOut:
    """Link a Clarity project to a GA4 property (or update the existing link for that property)."""
    settings = get_settings()
    pid = resolve_property_id(body.ga_property_id)  # only properties this dashboard can see
    token = _clean_token(body.api_token)
    project = project_for_property(db, pid)
    if project is None:
        if token:
            source, encrypted = "db", encrypt_token(settings, token)
        elif settings.mock_mode:
            source, encrypted = "mock", None
        elif pid in settings.clarity_token_map():
            source, encrypted = "env", None
        else:
            raise AppError(400, "clarity_token_required", "Enter the Clarity API token for this project.",
                           hint="Clarity → Settings → Data Export → Generate new API token.")
        project = ClarityProject(ga_property_id=pid, label=body.label.strip(), token_source=source,
                                 api_token_encrypted=encrypted, enabled=body.enabled)
        db.add(project)
    else:
        project.label = body.label.strip()
        project.enabled = body.enabled
        if token:
            project.api_token_encrypted, project.token_source = encrypt_token(settings, token), "db"
    db.commit()
    log.info("Clarity project for property %s saved (source=%s, enabled=%s)", pid, project.token_source, project.enabled)
    return project_out(db, project)


@router.patch("/clarity/projects/{project_id}", response_model=ClarityProjectOut)
def patch_project(project_id: int, body: ClarityProjectPatch, db: Session = Depends(get_db)) -> ClarityProjectOut:
    settings = get_settings()
    project = _get_project(db, project_id)
    if body.label is not None:
        project.label = body.label.strip()
    if body.enabled is not None:
        project.enabled = body.enabled
    token = _clean_token(body.api_token)
    if token:
        project.api_token_encrypted, project.token_source = encrypt_token(settings, token), "db"
    db.commit()
    return project_out(db, project)


@router.delete("/clarity/projects/{project_id}", response_model=ClarityProjectOut)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> ClarityProjectOut:
    """Unlink a project. Stored snapshots are kept (they belong to the GA property) and reappear if re-linked."""
    project = _get_project(db, project_id)
    if project.token_source == "env":
        raise AppError(400, "clarity_project_from_env", "This project comes from .env and would be re-created on restart.",
                       hint="Remove it from CLARITY_TOKENS / CLARITY_API_TOKEN, or disable it here instead.")
    out = project_out(db, project)
    db.delete(project)
    db.commit()
    log.info("Clarity project for property %s removed", project.ga_property_id)
    return out
