from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

Format = Literal["number", "percent", "duration", "decimal"]


def _as_utc(v: datetime | None) -> datetime | None:
    # SQLite drops tzinfo; stored values are always UTC.
    return v.replace(tzinfo=timezone.utc) if v is not None and v.tzinfo is None else v


UTCDateTime = Annotated[datetime, AfterValidator(_as_utc)]


class RangeInfo(BaseModel):
    start: date
    end: date


class KpiMetric(BaseModel):
    key: str
    label: str
    value: float | None
    previous: float | None = None
    change_pct: float | None = None
    format: Format = "number"


# ---------------------------------------------------------------- GA4
class GAOverview(BaseModel):
    range: RangeInfo
    previous_range: RangeInfo
    metrics: list[KpiMetric]


class TimeseriesPoint(BaseModel):
    date: date
    activeUsers: float
    sessions: float
    screenPageViews: float
    prev_date: date | None = None
    prev_activeUsers: float | None = None
    prev_sessions: float | None = None
    prev_screenPageViews: float | None = None


class GATimeseries(BaseModel):
    range: RangeInfo
    compare: bool
    points: list[TimeseriesPoint]


class ChannelRow(BaseModel):
    channel: str
    sessions: float
    activeUsers: float
    engagementRate: float
    keyEvents: float
    prev_sessions: float | None = None
    change_pct: float | None = None


class GAChannels(BaseModel):
    range: RangeInfo
    rows: list[ChannelRow]


class SourceRow(BaseModel):
    source: str
    medium: str
    sessions: float
    activeUsers: float
    engagementRate: float
    keyEvents: float


class GASources(BaseModel):
    range: RangeInfo
    rows: list[SourceRow]


class PageRow(BaseModel):
    pagePath: str
    pageTitle: str
    views: float
    users: float
    avgEngagementTime: float = Field(description="Seconds of engagement per user")


class GAPages(BaseModel):
    range: RangeInfo
    rows: list[PageRow]


class CountryRow(BaseModel):
    country: str
    activeUsers: float
    sessions: float


class CityRow(BaseModel):
    city: str
    country: str
    activeUsers: float


class GAGeo(BaseModel):
    range: RangeInfo
    countries: list[CountryRow]
    cities: list[CityRow]


class NameCount(BaseModel):
    name: str
    value: float


class GATech(BaseModel):
    range: RangeInfo
    devices: list[NameCount]
    browsers: list[NameCount]
    operatingSystems: list[NameCount]


class EventRow(BaseModel):
    eventName: str
    eventCount: float
    totalUsers: float


class GAEvents(BaseModel):
    range: RangeInfo
    rows: list[EventRow]


class GARealtime(BaseModel):
    activeUsers: float
    byCountry: list[NameCount]
    byDevice: list[NameCount]
    byPage: list[NameCount]
    fetched_at: datetime


# ---------------------------------------------------------------- Clarity
class ClarityDay(BaseModel):
    date: date
    sessions: float | None = None
    botSessions: float | None = None
    users: float | None = None
    pagesPerSession: float | None = None
    scrollDepth: float | None = None
    activeTime: float | None = None
    totalTime: float | None = None


class ClarityOverview(BaseModel):
    range: RangeInfo
    history_start: date | None
    latest_date: date | None
    kpis: list[KpiMetric]
    series: list[ClarityDay]
    backfill: ClarityDay | None = Field(None, description="Initial 3-day aggregate captured on first sync")


class FrustrationSignal(BaseModel):
    key: str
    label: str
    metric: str


class FrustrationPoint(BaseModel):
    date: date
    sessions: float | None = None
    dead_pct: float | None = None
    rage_pct: float | None = None
    quickback_pct: float | None = None
    excessive_scroll_pct: float | None = None
    error_click_pct: float | None = None
    script_error_pct: float | None = None
    dead_count: float | None = None
    rage_count: float | None = None
    quickback_count: float | None = None
    excessive_scroll_count: float | None = None
    error_click_count: float | None = None
    script_error_count: float | None = None


class ClarityPageRow(BaseModel):
    url: str
    path: str
    days: int
    sessions: float | None = None
    scrollDepth: float | None = None
    activeTime: float | None = None
    dead_pct: float | None = None
    rage_pct: float | None = None
    quickback_pct: float | None = None
    excessive_scroll_pct: float | None = None
    error_click_pct: float | None = None
    script_error_pct: float | None = None
    dead_count: float | None = None
    rage_count: float | None = None


class ClarityFrustration(BaseModel):
    range: RangeInfo
    history_start: date | None
    signals: list[FrustrationSignal]
    series: list[FrustrationPoint]
    by_page: list[ClarityPageRow]


class ClarityPages(BaseModel):
    range: RangeInfo
    history_start: date | None
    rows: list[ClarityPageRow]


class BreakdownRow(BaseModel):
    value: str
    sessions: float | None = None
    users: float | None = None
    scrollDepth: float | None = None
    activeTime: float | None = None
    dead_pct: float | None = None
    rage_pct: float | None = None


class ClarityBreakdown(BaseModel):
    dimension: str
    snapshot_date: date | None
    rows: list[BreakdownRow]


class SyncRunInfo(BaseModel):
    started_at: UTCDateTime
    finished_at: UTCDateTime | None
    trigger: str
    status: str
    calls_made: int
    snapshots_stored: int
    message: str


class ClarityStatus(BaseModel):
    property_id: str
    linked: bool = Field(description="A Clarity project is linked to this property")
    project: "ClarityProjectOut | None" = None
    mock_mode: bool
    token_configured: bool
    last_successful_sync: UTCDateTime | None
    last_run: SyncRunInfo | None
    calls_used_today: int
    daily_limit: int
    safety_limit: int
    calls_remaining: int
    sync_available: bool
    quota_exhausted: bool
    next_scheduled_run: datetime | None
    scheduler_enabled: bool
    history_start: date | None
    latest_snapshot: date | None
    utc_day: date


class ProjectSyncResult(BaseModel):
    property_id: str
    project_id: int
    label: str
    status: str
    calls_made: int
    snapshots_stored: int
    skipped: list[str]
    errors: list[str]
    message: str


class SyncResult(BaseModel):
    status: str
    calls_made: int
    snapshots_stored: int
    skipped: list[str]
    errors: list[str]
    message: str
    projects: list[ProjectSyncResult] = []


# ---------------------------------------------------------------- Combined
class CombinedPageRow(BaseModel):
    path: str
    pageTitle: str
    views: float
    users: float
    avgEngagementTime: float
    has_clarity: bool
    clarity_sessions: float | None = None
    scrollDepth: float | None = None
    dead_pct: float | None = None
    rage_pct: float | None = None
    quickback_pct: float | None = None
    error_click_pct: float | None = None
    dead_count: float | None = None
    rage_count: float | None = None
    frustration_score: float | None = None
    is_problem: bool = False
    problem_reasons: list[str] = []


class CombinedThresholds(BaseModel):
    min_views: float
    min_frustration_score: float


class CombinedPages(BaseModel):
    range: RangeInfo
    clarity_linked: bool = True
    clarity_history_start: date | None
    thresholds: CombinedThresholds
    rows: list[CombinedPageRow]


# ---------------------------------------------------------------- Misc
class LoginRequest(BaseModel):
    password: str


class AuthStatus(BaseModel):
    authenticated: bool
    mock_mode: bool


class ConnectionTest(BaseModel):
    source: Literal["ga", "clarity"]
    ok: bool
    message: str
    details: dict[str, str | int | float | bool | None] = {}


# ---------------------------------------------------------------- properties & Clarity projects
class PropertyOut(BaseModel):
    accountId: str
    accountName: str
    propertyId: str
    propertyName: str
    hasClarity: bool
    isDefault: bool = False


class ClarityProjectOut(BaseModel):
    id: int
    ga_property_id: str
    label: str
    enabled: bool
    token_source: Literal["db", "env", "mock"]
    has_token: bool
    created_at: UTCDateTime
    calls_used_today: int = 0
    quota_exhausted: bool = False
    last_run: SyncRunInfo | None = None


class ClarityProjectIn(BaseModel):
    ga_property_id: str = Field(pattern=r"^\d{1,20}$")
    label: str = Field("", max_length=200)
    api_token: str | None = Field(None, max_length=4000, description="Omit to keep the current token")
    enabled: bool = True


class ClarityProjectPatch(BaseModel):
    label: str | None = Field(None, max_length=200)
    api_token: str | None = Field(None, max_length=4000)
    enabled: bool | None = None


ClarityStatus.model_rebuild()
