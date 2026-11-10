"""Live site report (GA + stored Clarity) for a date range, as JSON or a printable HTML page."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.config import get_settings
from app.db import get_db
from app.deps import ga_for_property, selected_property
from app.services import report
from app.services.clarity_projects import project_for_property
from app.services.ga import GAService
from app.utils.dates import DateRange, date_range_params

router = APIRouter(prefix="/api/report", tags=["report"], dependencies=[Depends(require_auth)])


def _build(r: DateRange, label: str, property_id: str, ga: GAService, db: Session) -> dict[str, Any]:
    clarity_pid = property_id if project_for_property(db, property_id) is not None else None
    return report.build(ga, db, get_settings(), property_id, clarity_pid, r, label=label)


@router.get("")
def report_json(r: DateRange = Depends(date_range_params), label: str = Query("", max_length=60),
                property_id: str = Depends(selected_property), ga: GAService = Depends(ga_for_property),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    d = _build(r, label, property_id, ga, db)
    d["range"] = {"start": r.start, "end": r.end}
    d["previous"] = {"start": r.previous.start, "end": r.previous.end}
    return d


@router.get("/html", response_class=HTMLResponse)
def report_html(r: DateRange = Depends(date_range_params), label: str = Query("", max_length=60),
                property_id: str = Depends(selected_property), ga: GAService = Depends(ga_for_property),
                db: Session = Depends(get_db)) -> HTMLResponse:
    return HTMLResponse(report.render_html(_build(r, label, property_id, ga, db)),
                        headers={"Cache-Control": "no-store"})
