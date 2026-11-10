"""Deterministic fake GA4 data for MOCK_MODE. Same interface as GAService."""
from __future__ import annotations

import random
from datetime import date, datetime, timezone
from typing import Any

from app.schemas import (
    ChannelRow,
    CityRow,
    CountryRow,
    EventRow,
    GAChannels,
    GAEvents,
    GAGeo,
    GAOverview,
    GAPages,
    GARealtime,
    GASources,
    GATech,
    GATimeseries,
    KpiMetric,
    NameCount,
    PageRow,
    SourceRow,
    TimeseriesPoint,
)
from app.services import mock_data as md
from app.services.ga import OVERVIEW_METRICS, pct_change, rng
from app.utils.dates import DateRange

_BASE = date(2025, 1, 1).toordinal()
_WEEKDAY = [1.08, 1.1, 1.07, 1.04, 0.97, 0.78, 0.74]


def _day(d: date, property_id: str = "") -> dict[str, float]:
    """One day of fake GA totals. Each property gets its own scale and noise; "" is the base site."""
    r = random.Random(f"{property_id}|{d.toordinal()}" if property_id else d.toordinal())
    scale = md.mock_scale(property_id) if property_id else 1.0
    users = (820 + (d.toordinal() - _BASE) * 0.9) * scale * _WEEKDAY[d.weekday()] * r.uniform(0.9, 1.1)
    sessions = users * r.uniform(1.24, 1.38)
    engagement = r.uniform(0.55, 0.64)
    return {
        "activeUsers": round(users),
        "newUsers": round(users * r.uniform(0.58, 0.66)),
        "sessions": round(sessions),
        "screenPageViews": round(sessions * r.uniform(2.1, 2.6)),
        "engagementRate": engagement,
        "bounceRate": 1 - engagement,
        "averageSessionDuration": r.uniform(128, 168),
        "keyEvents": round(sessions * r.uniform(0.026, 0.036)),
    }


def _totals(r: DateRange, property_id: str = "") -> dict[str, float]:
    days = [_day(d, property_id) for d in r.iter_days()]
    s = sum(x["sessions"] for x in days) or 1
    out = {k: float(sum(x[k] for x in days)) for k in ("activeUsers", "newUsers", "sessions", "screenPageViews", "keyEvents")}
    # GA de-duplicates users across days; approximate that for multi-day ranges.
    if r.days > 1:
        out["activeUsers"] = round(out["activeUsers"] * 0.82)
        out["newUsers"] = round(out["newUsers"] * 0.9)
    for k in ("engagementRate", "bounceRate", "averageSessionDuration"):
        out[k] = sum(x[k] * x["sessions"] for x in days) / s
    return out


def _split(total: float, shares: list[float], seed: Any, jitter: float = 0.12) -> list[float]:
    r = random.Random(str(seed))
    weights = [w * r.uniform(1 - jitter, 1 + jitter) for w in shares]
    z = sum(weights)
    return [round(total * w / z) for w in weights]


class MockGAService:
    def __init__(self, property_id: str = "") -> None:
        self.property_id = property_id

    def _totals(self, r: DateRange) -> dict[str, float]:
        return _totals(r, self.property_id)

    def _day(self, d: date) -> dict[str, float]:
        return _day(d, self.property_id)

    def overview(self, r: DateRange) -> GAOverview:
        cur, prev = self._totals(r), self._totals(r.previous)
        return GAOverview(range=rng(r), previous_range=rng(r.previous), metrics=[
            KpiMetric(key=k, label=label, value=cur[k], previous=prev[k], change_pct=pct_change(cur[k], prev[k]), format=fmt)  # type: ignore[arg-type]
            for k, label, fmt in OVERVIEW_METRICS
        ])

    def timeseries(self, r: DateRange) -> GATimeseries:
        points = []
        prev_days = r.previous.iter_days()
        for i, d in enumerate(r.iter_days()):
            x = self._day(d)
            p = TimeseriesPoint(date=d, activeUsers=x["activeUsers"], sessions=x["sessions"], screenPageViews=x["screenPageViews"])
            if r.compare:
                y = self._day(prev_days[i])
                p.prev_date, p.prev_activeUsers, p.prev_sessions, p.prev_screenPageViews = (
                    prev_days[i], y["activeUsers"], y["sessions"], y["screenPageViews"])
            points.append(p)
        return GATimeseries(range=rng(r), compare=r.compare, points=points)

    def channels(self, r: DateRange) -> GAChannels:
        t, tp = self._totals(r), self._totals(r.previous)
        shares = [s for _, s in md.CHANNELS]
        cur = _split(t["sessions"], shares, (r.start, r.end, "ch"))
        prev = _split(tp["sessions"], shares, (r.previous.start, r.previous.end, "ch"))
        rows = []
        for (name, _), s, ps in zip(md.CHANNELS, cur, prev):
            rr = random.Random(name + str(r.start))
            rows.append(ChannelRow(channel=name, sessions=s, activeUsers=round(s * 0.79), engagementRate=rr.uniform(0.45, 0.72),
                                   keyEvents=round(s * rr.uniform(0.015, 0.05)), prev_sessions=ps if r.compare else None,
                                   change_pct=pct_change(s, ps) if r.compare else None))
        rows.sort(key=lambda x: -x.sessions)
        return GAChannels(range=rng(r), rows=rows)

    def sources(self, r: DateRange) -> GASources:
        t = self._totals(r)
        vals = _split(t["sessions"], [s for *_, s in md.SOURCES], (r.start, r.end, "src"))
        rows = []
        for (src, med, _), s in zip(md.SOURCES, vals):
            rr = random.Random(src + med + str(r.start))
            rows.append(SourceRow(source=src, medium=med, sessions=s, activeUsers=round(s * 0.8),
                                  engagementRate=rr.uniform(0.4, 0.75), keyEvents=round(s * rr.uniform(0.01, 0.05))))
        rows.sort(key=lambda x: -x.sessions)
        return GASources(range=rng(r), rows=rows)

    def pages(self, r: DateRange, limit: int = 50) -> GAPages:
        t = self._totals(r)
        vals = _split(t["screenPageViews"], [p.weight for p in md.MOCK_PAGES], (r.start, r.end, "pages"))
        rows = []
        for p, v in zip(md.MOCK_PAGES, vals):
            rr = random.Random(p.path + str(r.start))
            rows.append(PageRow(pagePath=p.path, pageTitle=p.title, views=v, users=round(v * rr.uniform(0.55, 0.75)),
                                avgEngagementTime=round(rr.uniform(18, 140), 1)))
        rows.sort(key=lambda x: -x.views)
        return GAPages(range=rng(r), rows=rows[:limit])

    def geo(self, r: DateRange) -> GAGeo:
        t = self._totals(r)
        users = _split(t["activeUsers"], [s for _, s, _ in md.COUNTRIES], (r.start, r.end, "geo"))
        countries, cities = [], []
        for (name, _, city_names), u in zip(md.COUNTRIES, users):
            countries.append(CountryRow(country=name, activeUsers=u, sessions=round(u * 1.3)))
            weights = [1 / (i + 1.4) for i in range(len(city_names))]
            for c, cu in zip(city_names, _split(u * 0.85, weights, name)):
                cities.append(CityRow(city=c, country=name, activeUsers=cu))
        cities.sort(key=lambda x: -x.activeUsers)
        return GAGeo(range=rng(r), countries=countries, cities=cities[:50])

    def tech(self, r: DateRange) -> GATech:
        u = self._totals(r)["activeUsers"]

        def nc(items: list[tuple[str, float]], tag: str) -> list[NameCount]:
            return [NameCount(name=n, value=v) for (n, _), v in zip(items, _split(u, [s for _, s in items], (r.start, tag), 0.05))]

        return GATech(range=rng(r), devices=nc(md.DEVICES, "dev"), browsers=nc(md.BROWSERS, "br"), operatingSystems=nc(md.OSES, "os"))

    def events(self, r: DateRange) -> GAEvents:
        t = self._totals(r)
        rows = []
        for name, per_session in md.EVENTS:
            rr = random.Random(name + str(r.start))
            count = round(t["sessions"] * per_session * rr.uniform(0.92, 1.08))
            rows.append(EventRow(eventName=name, eventCount=count, totalUsers=round(min(count, t["activeUsers"]) * rr.uniform(0.5, 0.95))))
        rows.sort(key=lambda x: -x.eventCount)
        return GAEvents(range=rng(r), rows=rows)

    def realtime(self) -> GARealtime:
        now = datetime.now(timezone.utc)
        r = random.Random(self.property_id + now.strftime("%Y%m%d%H%M"))
        total = max(1, round(r.randint(28, 64) * md.mock_scale(self.property_id))) if self.property_id else r.randint(28, 64)

        def nc(items: list[tuple[str, float]]) -> list[NameCount]:
            return [NameCount(name=n, value=v) for (n, _), v in zip(items, _split(total, [s for _, s in items], r.random(), 0.3)) if v > 0]

        return GARealtime(
            activeUsers=total,
            byCountry=nc([(c, s) for c, s, _ in md.COUNTRIES[:6]]),
            byDevice=nc(md.DEVICES),
            byPage=nc([(p.title, p.weight) for p in md.MOCK_PAGES[:8]]),
            fetched_at=now,
        )

    def test_connection(self) -> dict[str, Any]:
        return {"activeUsers": 1234.0, "sessions": 1650.0, "mock": True}
