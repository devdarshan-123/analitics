"""Request dependencies shared by the property-aware routers."""
from __future__ import annotations

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import ClarityProject
from app.services.clarity_projects import project_for_property
from app.services.ga import GAService, get_ga_service
from app.services.properties import resolve_property_id

PROPERTY_PATTERN = r"^\d{1,20}$"


def selected_property(
    propertyId: str | None = Query(None, pattern=PROPERTY_PATTERN,  # noqa: N803 — public API name
                                   description="Numeric GA4 property ID; defaults to the default property"),
) -> str:
    """The requested property, validated against the discovered list (403 for anything else)."""
    return resolve_property_id(propertyId)


def ga_for_property(property_id: str = Depends(selected_property)) -> GAService:
    return get_ga_service(property_id)


def linked_clarity_project(property_id: str = Depends(selected_property), db: Session = Depends(get_db)) -> ClarityProject:
    """The property's Clarity project (enabled or not, so stored history stays readable); 404 if none."""
    project = project_for_property(db, property_id)
    if project is None:
        raise AppError(404, "clarity_not_linked", f"No Clarity project is linked to GA4 property {property_id}.",
                       hint="Link one in Settings → Clarity projects (or add it to CLARITY_TOKENS in .env).")
    return project
