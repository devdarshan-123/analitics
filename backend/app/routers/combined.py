from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_db
from app.deps import selected_property
from app.schemas import CombinedPages
from app.services import clarity_queries as q
from app.services.clarity_projects import project_for_property
from app.services.combined import combine_pages
from app.services.ga import get_ga_service
from app.utils.dates import DateRange, date_range_params

router = APIRouter(prefix="/api/combined", tags=["combined"], dependencies=[Depends(require_auth)])


@router.get("/pages", response_model=CombinedPages)
def combined_pages(r: DateRange = Depends(date_range_params), property_id: str = Depends(selected_property),
                   db: Session = Depends(get_db)) -> CombinedPages:
    ga_pages = get_ga_service(property_id).pages(r, limit=50)
    if project_for_property(db, property_id) is None:
        # GA-only view: no Clarity project for this property, so nothing to join or flag.
        result = combine_pages(ga_pages, [], None)
        result.clarity_linked = False
        return result
    return combine_pages(ga_pages, q.pages(db, property_id, r), q.history_start(db, property_id))
