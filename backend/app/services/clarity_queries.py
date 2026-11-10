"""Read-side aggregations over stored Clarity snapshots. Never calls the Clarity API."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ClarityMetric, ClarityRawSnapshot
from app.schemas import (
    BreakdownRow,
    ClarityBreakdown,
    ClarityDay,
    ClarityFrustration,
    ClarityOverview,
    ClarityPageRow,
    ClarityPages,
    FrustrationPoint,
    FrustrationSignal,
    KpiMetric,
    RangeInfo,
)
from app.services.ga import pct_change
from app.utils.dates import DateRange
from app.utils.paths import normalize_path

FRUSTRATION = [
    ("dead", "Dead clicks", "DeadClickCount"),
    ("rage", "Rage clicks", "RageClickCount"),
    ("quickback", "Quick backs", "QuickbackClick"),
    ("excessive_scroll", "Excessive scrolling", "ExcessiveScroll"),
    ("error_click", "Error clicks", "ErrorClickCount"),
    ("script_error", "Script errors", "ScriptErrorCount"),
]
BREAKDOWN_DIMENSIONS = {"Device": "Device", "Source": "Source", "Country": "Country/Region"}

# metric -> field(lower) -> value
Fields = dict[str, dict[str, float]]


def pick(fields: Fields, metric: str, *names: str) -> float | None:
    m = fields.get(metric, {})
    for n in names:
        if n.lower() in m:
            return m[n.lower()]
    return None


def _load(db: Session, pid: str, dims: str, start: date | None, end: date | None,
          num_of_days: int = 1) -> dict[date, dict[str, Fields]]:
    """date -> dimension value -> metric -> field -> value, for one property's stored dimension set."""
    q = select(ClarityMetric.snapshot_date, ClarityMetric.dimension_key, ClarityMetric.dimension_value,
               ClarityMetric.metric_name, ClarityMetric.field_name, ClarityMetric.value).where(
        ClarityMetric.property_id == pid, ClarityMetric.dimensions == dims, ClarityMetric.num_of_days == num_of_days)
    if start:
        q = q.where(ClarityMetric.snapshot_date >= start)
    if end:
        q = q.where(ClarityMetric.snapshot_date <= end)
    out: dict[date, dict[str, Fields]] = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for d, dkey, dval, metric, fname, value in db.execute(q):
        # Totals snapshots also contain name/count lists (Browser, Referrer…); only keep rows whose
        # dimension matches the snapshot's own dimension set.
        if dkey.lower() != dims.lower():
            continue
        out[d][dval][metric][fname.lower()] = value
    return out


def _day(d: date, f: Fields) -> ClarityDay:
    return ClarityDay(
        date=d,
        sessions=pick(f, "Traffic", "totalSessionCount"),
        botSessions=pick(f, "Traffic", "totalBotSessionCount"),
        users=pick(f, "Traffic", "distinctUserCount", "distantUserCount"),
        pagesPerSession=pick(f, "Traffic", "pagesPerSessionPercentage", "pagesPerSession"),
        scrollDepth=pick(f, "ScrollDepth", "averageScrollDepth"),
        activeTime=pick(f, "EngagementTime", "activeTime"),
        totalTime=pick(f, "EngagementTime", "totalTime"),
    )


def _wavg(pairs: list[tuple[float | None, float | None]]) -> float | None:
    """Weighted average ignoring missing values; falls back to equal weights."""
    vals = [(v, w or 0.0) for v, w in pairs if v is not None]
    if not vals:
        return None
    total_w = sum(w for _, w in vals)
    if total_w <= 0:
        return sum(v for v, _ in vals) / len(vals)
    return sum(v * w for v, w in vals) / total_w


def _sum(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def history_start(db: Session, pid: str) -> date | None:
    base = select(func.min(ClarityRawSnapshot.snapshot_date)).where(ClarityRawSnapshot.property_id == pid)
    daily = db.execute(base.where(ClarityRawSnapshot.num_of_days == 1)).scalar()
    backfill = db.execute(base.where(ClarityRawSnapshot.num_of_days == 3)).scalar()
    candidates = [d for d in (daily, backfill - timedelta(days=2) if backfill else None) if d]
    return min(candidates) if candidates else None


def latest_snapshot(db: Session, pid: str) -> date | None:
    return db.execute(select(func.max(ClarityRawSnapshot.snapshot_date)).where(ClarityRawSnapshot.property_id == pid)).scalar()


def _range(r: DateRange) -> RangeInfo:
    return RangeInfo(start=r.start, end=r.end)


# ---------------------------------------------------------------- overview
def _summarise(days: list[ClarityDay]) -> dict[str, float | None]:
    return {
        "sessions": _sum([d.sessions for d in days]),
        "users": _sum([d.users for d in days]),
        "pagesPerSession": _wavg([(d.pagesPerSession, d.sessions) for d in days]),
        "scrollDepth": _wavg([(d.scrollDepth, d.sessions) for d in days]),
        "activeTime": _wavg([(d.activeTime, d.sessions) for d in days]),
    }


KPI_DEFS = [
    ("sessions", "Sessions", "number"),
    ("users", "Users", "number"),
    ("pagesPerSession", "Pages / session", "decimal"),
    ("scrollDepth", "Avg. scroll depth (%)", "decimal"),
    ("activeTime", "Active time / session", "duration"),
]


def overview(db: Session, pid: str, r: DateRange) -> ClarityOverview:
    def days_for(dr: DateRange) -> list[ClarityDay]:
        data = _load(db, pid, "", dr.start, dr.end)
        return [_day(d, data[d].get("", {})) for d in sorted(data)]

    series = days_for(r)
    cur = _summarise(series)
    prev_days = days_for(r.previous)
    # Only compare when the previous period is as well covered as this one; otherwise a period that
    # straddles the start of history (e.g. 1 stored day vs 30) produces meaningless +3000% changes.
    prev = _summarise(prev_days) if prev_days and len(prev_days) >= len(series) else {}
    kpis = [
        KpiMetric(key=key, label=label, value=cur[key], previous=prev.get(key),
                  change_pct=pct_change(cur[key], prev.get(key)), format=fmt)  # type: ignore[arg-type]
        for key, label, fmt in KPI_DEFS
    ]

    backfill = None
    bf = db.execute(select(ClarityRawSnapshot.snapshot_date).where(
        ClarityRawSnapshot.property_id == pid, ClarityRawSnapshot.num_of_days == 3, ClarityRawSnapshot.dimensions == "")
        .order_by(ClarityRawSnapshot.snapshot_date)).scalar()
    if bf:
        data = _load(db, pid, "", bf, bf, num_of_days=3)
        backfill = _day(bf, data[bf].get("", {}))
    return ClarityOverview(range=_range(r), history_start=history_start(db, pid), latest_date=latest_snapshot(db, pid), kpis=kpis,
                           series=series, backfill=backfill)


# ---------------------------------------------------------------- pages
def _frustration_fields(f: Fields) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key, _, metric in FRUSTRATION:
        out[f"{key}_pct"] = pick(f, metric, "sessionsWithMetricPercentage")
        out[f"{key}_count"] = pick(f, metric, "subTotal", "count")
    return out


def pages(db: Session, pid: str, r: DateRange) -> list[ClarityPageRow]:
    data = _load(db, pid, "URL", r.start, r.end)
    groups: dict[str, list[tuple[date, str, Fields]]] = defaultdict(list)
    for d, by_url in data.items():
        for url, f in by_url.items():
            groups[normalize_path(url)].append((d, url, f))

    rows: list[ClarityPageRow] = []
    for path, items in groups.items():
        entries = []
        for d, url, f in items:
            sessions = pick(f, "Traffic", "totalSessionCount")
            entries.append((d, url, sessions, f, _frustration_fields(f)))
        url_sessions: dict[str, float] = defaultdict(float)
        for _, url, s, _, _ in entries:
            url_sessions[url] += s or 0
        row: dict[str, Any] = {
            "url": max(url_sessions, key=url_sessions.get),
            "path": path,
            "days": len({e[0] for e in entries}),
            "sessions": _sum([e[2] for e in entries]),
            "scrollDepth": _wavg([(pick(e[3], "ScrollDepth", "averageScrollDepth"), e[2]) for e in entries]),
            "activeTime": _wavg([(pick(e[3], "EngagementTime", "activeTime"), e[2]) for e in entries]),
        }
        for key, _, _ in FRUSTRATION:
            row[f"{key}_pct"] = _wavg([(e[4][f"{key}_pct"], e[2]) for e in entries])
        row["dead_count"] = _sum([e[4]["dead_count"] for e in entries])
        row["rage_count"] = _sum([e[4]["rage_count"] for e in entries])
        rows.append(ClarityPageRow(**{k: round(v, 2) if isinstance(v, float) else v for k, v in row.items()}))
    rows.sort(key=lambda x: -(x.sessions or 0))
    return rows


def pages_response(db: Session, pid: str, r: DateRange) -> ClarityPages:
    return ClarityPages(range=_range(r), history_start=history_start(db, pid), rows=pages(db, pid, r))


# ---------------------------------------------------------------- frustration
def frustration(db: Session, pid: str, r: DateRange) -> ClarityFrustration:
    data = _load(db, pid, "", r.start, r.end)
    series = []
    for d in sorted(data):
        f = data[d].get("", {})
        series.append(FrustrationPoint(date=d, sessions=pick(f, "Traffic", "totalSessionCount"), **_frustration_fields(f)))
    by_page = sorted(pages(db, pid, r), key=lambda p: -((p.rage_count or 0) * 2 + (p.dead_count or 0)))[:25]
    return ClarityFrustration(
        range=_range(r), history_start=history_start(db, pid),
        signals=[FrustrationSignal(key=k, label=label, metric=m) for k, label, m in FRUSTRATION],
        series=series, by_page=by_page,
    )


# ---------------------------------------------------------------- breakdown
def breakdown(db: Session, pid: str, dimension: str) -> ClarityBreakdown:
    dims = BREAKDOWN_DIMENSIONS[dimension]
    latest = db.execute(select(func.max(ClarityRawSnapshot.snapshot_date)).where(
        ClarityRawSnapshot.property_id == pid, ClarityRawSnapshot.dimensions == dims, ClarityRawSnapshot.num_of_days == 1)).scalar()
    if latest is None:
        return ClarityBreakdown(dimension=dimension, snapshot_date=None, rows=[])
    data = _load(db, pid, dims, latest, latest).get(latest, {})
    rows = []
    for value, f in data.items():
        day = _day(latest, f)
        fr = _frustration_fields(f)
        rows.append(BreakdownRow(value=value or "(not set)", sessions=day.sessions, users=day.users, scrollDepth=day.scrollDepth,
                                 activeTime=day.activeTime, dead_pct=fr["dead_pct"], rage_pct=fr["rage_pct"]))
    rows.sort(key=lambda x: -(x.sessions or 0))
    return ClarityBreakdown(dimension=dimension, snapshot_date=latest, rows=rows)
