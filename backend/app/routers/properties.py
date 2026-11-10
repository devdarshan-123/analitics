from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.config import get_settings
from app.db import get_db
from app.schemas import PropertyOut
from app.services.clarity_projects import linked_property_ids
from app.services.properties import get_directory

router = APIRouter(prefix="/api", tags=["properties"], dependencies=[Depends(require_auth)])


@router.get("/properties", response_model=list[PropertyOut])
def list_properties(refresh: bool = Query(False, description="Bypass the 1-hour cache and re-query the Admin API"),
                    db: Session = Depends(get_db)) -> list[PropertyOut]:
    """Every GA4 property the service account can read, sorted by account name then property name."""
    directory = get_directory()
    props = directory.list(refresh=refresh)
    default = directory.default_id(get_settings().ga4_property_id)
    linked = linked_property_ids(db)
    return [PropertyOut(accountId=p.account_id, accountName=p.account_name, propertyId=p.property_id,
                        propertyName=p.property_name, hasClarity=p.property_id in linked, isDefault=p.property_id == default)
            for p in props]
