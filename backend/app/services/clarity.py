"""Microsoft Clarity Data Export API: HTTP client, defensive parser, daily quota guard and storage.

The API allows 10 requests per project per day and only returns the last 1-3 days, so the
dashboard never calls it on page load; app.jobs.clarity_sync does, and everything else reads the DB.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Protocol

import httpx
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models import ClarityApiUsage, ClarityMetric, ClarityRawSnapshot

log = logging.getLogger("app.clarity")

KNOWN_METRICS = {
    "Traffic", "EngagementTime", "ScrollDepth", "PopularPages", "Referrer", "DeadClickCount", "RageClickCount",
    "QuickbackClick", "ExcessiveScroll", "ErrorClickCount", "ScriptErrorCount", "Browser", "Device", "OS",
    "Country", "PageTitle",
}
KNOWN_FIELDS = {
    "totalsessioncount", "totalbotsessioncount", "distantusercount", "distinctusercount", "pagespersessionpercentage",
    "pagespersession", "averagescrolldepth", "totaltime", "activetime", "sessionscount", "sessionswithmetricpercentage",
    "sessionswithoutmetricpercentage", "pagesviews", "subtotal", "visitscount",
}
# Canonical spelling of fields that are always dimension values, even when they look numeric.
DIMENSION_FIELDS = {
    d.lower(): d for d in (
        "Browser", "Device", "Country/Region", "Country", "OS", "Source", "Medium", "Campaign", "Channel", "URL",
        "PageTitle", "ReferrerUrl", "name",
    )
}
ALLOWED_DIMENSIONS = {"Browser", "Device", "Country/Region", "OS", "Source", "Medium", "Campaign", "Channel", "URL",
                      "PageTitle", "ReferrerUrl"}


def dims_key(dimensions: list[str] | tuple[str, ...]) -> str:
    return "|".join(dimensions)


# ---------------------------------------------------------------- parser
@dataclass
class ParsedValue:
    metric_name: str
    dimension_key: str
    dimension_value: str
    field_name: str
    value: float


@dataclass
class ParseResult:
    values: list[ParsedValue] = field(default_factory=list)
    unknown_metrics: set[str] = field(default_factory=set)
    unknown_fields: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


def _to_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if s.endswith("%"):
            s = s[:-1]
        try:
            return float(s)
        except ValueError:
            return None
    return None


def parse_live_insights(payload: Any) -> ParseResult:
    """Normalise a project-live-insights response into flat values. Never raises on odd input."""
    result = ParseResult()
    if isinstance(payload, dict):
        # Tolerate a wrapped list ({"data": [...]}) or a single metric object.
        inner = next((v for v in payload.values() if isinstance(v, list)), None)
        payload = inner if inner is not None else [payload]
    if not isinstance(payload, list):
        result.warnings.append(f"Unexpected payload type {type(payload).__name__}; nothing parsed")
        log.warning(result.warnings[-1])
        return result

    for i, block in enumerate(payload):
        if not isinstance(block, dict):
            result.warnings.append(f"Item {i} is not an object; skipped")
            continue
        metric = str(block.get("metricName") or block.get("metric_name") or f"unknown_{i}")
        if metric not in KNOWN_METRICS:
            result.unknown_metrics.add(metric)
        info = block.get("information", [])
        if isinstance(info, dict):
            info = [info]
        if not isinstance(info, list):
            result.warnings.append(f"{metric}: 'information' is {type(info).__name__}; skipped")
            continue
        for row in info:
            if not isinstance(row, dict):
                result.warnings.append(f"{metric}: non-object row skipped")
                continue
            dim_keys: list[str] = []
            dim_vals: list[str] = []
            numeric: list[tuple[str, float]] = []
            for k, v in row.items():
                canonical = DIMENSION_FIELDS.get(k.lower())
                num = None if canonical else _to_number(v)
                if canonical or (isinstance(v, str) and num is None):
                    dim_keys.append(canonical or k)
                    dim_vals.append("" if v is None else str(v))
                elif num is not None:
                    numeric.append((k, num))
                    if k.lower() not in KNOWN_FIELDS:
                        result.unknown_fields.add(f"{metric}.{k}")
                elif v is not None:
                    result.warnings.append(f"{metric}.{k}: unsupported value type {type(v).__name__}; kept in raw only")
            for k, num in numeric:
                result.values.append(ParsedValue(metric, "|".join(dim_keys), "|".join(dim_vals), k, num))

    if result.unknown_metrics:
        log.warning("Clarity parser: unknown metric names kept: %s", sorted(result.unknown_metrics))
    if result.unknown_fields:
        log.info("Clarity parser: unrecognised fields kept: %s", sorted(result.unknown_fields))
    for w in result.warnings[:20]:
        log.warning("Clarity parser: %s", w)
    return result


# ---------------------------------------------------------------- HTTP client
class ClarityError(Exception):
    pass


class ClarityQuotaExceeded(ClarityError):
    pass


class ClarityAuthError(ClarityError):
    pass


class ClarityFetcher(Protocol):
    def fetch(self, num_of_days: int, dimensions: list[str]) -> Any: ...


class ClarityClient:
    def __init__(self, token: str, base_url: str, timeout: float = 30.0, transport: httpx.BaseTransport | None = None) -> None:
        self._token = token
        self.base_url = base_url
        self.timeout = timeout
        self.transport = transport

    def fetch(self, num_of_days: int, dimensions: list[str]) -> Any:
        if num_of_days not in (1, 2, 3):
            raise ValueError("numOfDays must be 1, 2 or 3")
        if len(dimensions) > 3:
            raise ValueError("Clarity supports at most 3 dimensions")
        if not self._token:
            raise ClarityAuthError("No Clarity API token is configured for this project")
        params: dict[str, Any] = {"numOfDays": num_of_days}
        for i, d in enumerate(dimensions, start=1):
            params[f"dimension{i}"] = d
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.get(self.base_url, params=params,
                                  headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"})
        except httpx.HTTPError as e:
            log.error("Clarity GET %s params=%s status=network-error duration=%.0fms error=%s",
                      self.base_url, params, (time.perf_counter() - started) * 1000, type(e).__name__)
            raise ClarityError(f"Network error calling Clarity: {type(e).__name__}") from e
        log.info("Clarity GET %s params=%s status=%s duration=%.0fms", self.base_url, params, resp.status_code,
                 (time.perf_counter() - started) * 1000)
        if resp.status_code == 429:
            raise ClarityQuotaExceeded("Clarity daily quota (10 requests/project/day) is used up")
        if resp.status_code in (401, 403):
            raise ClarityAuthError(f"Clarity rejected the API token (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise ClarityError(f"Clarity HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as e:
            raise ClarityError("Clarity returned invalid JSON") from e


# ---------------------------------------------------------------- quota guard (per Clarity project)
def utc_today(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()


def get_usage(db: Session, project_id: int, now: datetime | None = None) -> ClarityApiUsage | None:
    return db.get(ClarityApiUsage, (project_id, utc_today(now)))


def calls_used_today(db: Session, project_id: int, now: datetime | None = None) -> int:
    usage = get_usage(db, project_id, now)
    return usage.calls if usage else 0


def try_reserve_call(db: Session, project_id: int, safety_limit: int, now: datetime | None = None) -> bool:
    """Count one API call against this project's budget for today (UTC). Returns False — without
    counting — once `safety_limit` calls have been used or Clarity has reported the quota as exhausted."""
    day = utc_today(now)
    usage = db.execute(select(ClarityApiUsage).where(ClarityApiUsage.clarity_project_id == project_id,
                                                     ClarityApiUsage.day == day).with_for_update()).scalar_one_or_none()
    if usage is None:
        usage = ClarityApiUsage(clarity_project_id=project_id, day=day, calls=0, exhausted=False)
        db.add(usage)
    if usage.exhausted or usage.calls >= safety_limit:
        db.rollback()
        return False
    usage.calls += 1
    db.commit()
    return True


def mark_exhausted(db: Session, project_id: int, daily_limit: int, now: datetime | None = None) -> None:
    day = utc_today(now)
    usage = db.get(ClarityApiUsage, (project_id, day)) or ClarityApiUsage(clarity_project_id=project_id, day=day, calls=0)
    usage.exhausted = True
    usage.calls = max(usage.calls, daily_limit)
    db.add(usage)
    db.commit()


# ---------------------------------------------------------------- storage (scoped to a GA property)
def snapshot_exists(db: Session, property_id: str, snapshot_date: date, dimensions: list[str], num_of_days: int) -> bool:
    return db.execute(
        select(ClarityRawSnapshot.id).where(
            ClarityRawSnapshot.property_id == property_id,
            ClarityRawSnapshot.snapshot_date == snapshot_date,
            ClarityRawSnapshot.dimensions == dims_key(dimensions),
            ClarityRawSnapshot.num_of_days == num_of_days,
        )
    ).first() is not None


def store_snapshot(
    db: Session, property_id: str, snapshot_date: date, dimensions: list[str], num_of_days: int, payload: Any,
    fetched_at: datetime | None = None, project_id: int | None = None,
) -> tuple[ClarityRawSnapshot, ParseResult]:
    """Persist the raw payload and its normalised values for one property. Caller commits."""
    key = dims_key(dimensions)
    snap = ClarityRawSnapshot(property_id=property_id, clarity_project_id=project_id, snapshot_date=snapshot_date,
                              dimensions=key, num_of_days=num_of_days, payload=payload,
                              fetched_at=fetched_at or datetime.now(timezone.utc))
    db.add(snap)
    db.flush()
    parsed = parse_live_insights(payload)
    if parsed.values:
        db.execute(insert(ClarityMetric), [
            dict(snapshot_id=snap.id, property_id=property_id, clarity_project_id=project_id, snapshot_date=snapshot_date,
                 num_of_days=num_of_days, dimensions=key, metric_name=v.metric_name, dimension_key=v.dimension_key,
                 dimension_value=v.dimension_value, field_name=v.field_name, value=v.value)
            for v in parsed.values
        ])
    return snap, parsed
