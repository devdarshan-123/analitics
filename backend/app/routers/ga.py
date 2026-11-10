from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.schemas import GAChannels, GAEvents, GAGeo, GAOverview, GAPages, GARealtime, GASources, GATech, GATimeseries
from app.deps import ga_for_property
from app.services.ga import GAService
from app.utils.dates import DateRange, date_range_params

router = APIRouter(prefix="/api/ga", tags=["ga"], dependencies=[Depends(require_auth)])

# Plain `def` endpoints: the GA client is blocking gRPC, so FastAPI runs these in its threadpool.


@router.get("/overview", response_model=GAOverview)
def overview(r: DateRange = Depends(date_range_params), ga: GAService = Depends(ga_for_property)) -> GAOverview:
    return ga.overview(r)


@router.get("/timeseries", response_model=GATimeseries)
def timeseries(r: DateRange = Depends(date_range_params), ga: GAService = Depends(ga_for_property)) -> GATimeseries:
    return ga.timeseries(r)


@router.get("/channels", response_model=GAChannels)
def channels(r: DateRange = Depends(date_range_params), ga: GAService = Depends(ga_for_property)) -> GAChannels:
    return ga.channels(r)


@router.get("/sources", response_model=GASources)
def sources(r: DateRange = Depends(date_range_params), ga: GAService = Depends(ga_for_property)) -> GASources:
    return ga.sources(r)


@router.get("/pages", response_model=GAPages)
def pages(r: DateRange = Depends(date_range_params), ga: GAService = Depends(ga_for_property)) -> GAPages:
    return ga.pages(r)


@router.get("/geo", response_model=GAGeo)
def geo(r: DateRange = Depends(date_range_params), ga: GAService = Depends(ga_for_property)) -> GAGeo:
    return ga.geo(r)


@router.get("/tech", response_model=GATech)
def tech(r: DateRange = Depends(date_range_params), ga: GAService = Depends(ga_for_property)) -> GATech:
    return ga.tech(r)


@router.get("/events", response_model=GAEvents)
def events(r: DateRange = Depends(date_range_params), ga: GAService = Depends(ga_for_property)) -> GAEvents:
    return ga.events(r)


@router.get("/realtime", response_model=GARealtime)
def realtime(ga: GAService = Depends(ga_for_property)) -> GARealtime:
    return ga.realtime()
