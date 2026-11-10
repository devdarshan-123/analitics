"""Google Analytics 4 Data API service (BetaAnalyticsDataClient) with caching and error mapping."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from google.analytics.data_v1beta.types import (
    DateRange as GADateRange,
    Dimension,
    Metric,
    OrderBy,
    RunRealtimeReportRequest,
    RunReportRequest,
)
from google.api_core import exceptions as gexc

from app.cache import TTLCache
from app.config import get_settings
from app.errors import AppError
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
    RangeInfo,
    SourceRow,
    TimeseriesPoint,
)
from app.utils.dates import DateRange

log = logging.getLogger("app.ga")

OVERVIEW_METRICS: list[tuple[str, str, str]] = [
    ("activeUsers", "Active users", "number"),
    ("newUsers", "New users", "number"),
    ("sessions", "Sessions", "number"),
    ("screenPageViews", "Page views", "number"),
    ("averageSessionDuration", "Avg. session duration", "duration"),
    ("engagementRate", "Engagement rate", "percent"),
    ("bounceRate", "Bounce rate", "percent"),
    ("keyEvents", "Key events", "number"),
]


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or not previous:
        return None
    return round((current - previous) / previous * 100, 2)


def rng(r: DateRange) -> RangeInfo:
    return RangeInfo(start=r.start, end=r.end)


def map_ga_error(e: Exception, property_id: str) -> AppError:
    detail = getattr(e, "message", None) or str(e)
    if isinstance(e, gexc.PermissionDenied):
        return AppError(
            403,
            "ga_permission_denied",
            f"GA permission denied for property {property_id} — add the service account as a Viewer on the property.",
            hint=f"GA Admin → Property access management → add the service-account email as Viewer on property "
            f"{property_id}. Also make sure the Google Analytics Data API is enabled. ({detail})",
        )
    if isinstance(e, gexc.ResourceExhausted):
        return AppError(429, "ga_quota_exceeded", "GA4 API quota exhausted — try again later.", hint=detail)
    if isinstance(e, gexc.Unauthenticated):
        return AppError(502, "ga_unauthenticated", "GA rejected the service-account credentials.", hint=detail)
    if isinstance(e, gexc.NotFound):
        return AppError(404, "ga_property_not_found", f"GA4 property {property_id} not found.",
                        hint="Property IDs are numeric (not the G-XXXX measurement ID). Refresh the property list if it was deleted.")
    if isinstance(e, gexc.InvalidArgument):
        return AppError(400, "ga_invalid_request", "GA rejected the report request.", hint=detail)
    return AppError(502, "ga_upstream_error", "Google Analytics API error.", hint=detail)


def _num(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_rows(resp: Any) -> list[dict[str, Any]]:
    dnames = [h.name for h in resp.dimension_headers]
    mnames = [h.name for h in resp.metric_headers]
    rows: list[dict[str, Any]] = []
    for row in resp.rows:
        item: dict[str, Any] = {n: v.value for n, v in zip(dnames, row.dimension_values)}
        item.update({n: _num(v.value) for n, v in zip(mnames, row.metric_values)})
        rows.append(item)
    return rows


def make_data_client(credentials_path: Path | None) -> Any:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.auth.exceptions import DefaultCredentialsError

    try:
        if credentials_path:
            if not credentials_path.exists():
                raise AppError(503, "ga_credentials_missing", f"Service-account key file not found: {credentials_path}",
                               hint="Check GOOGLE_APPLICATION_CREDENTIALS in .env.")
            return BetaAnalyticsDataClient.from_service_account_file(str(credentials_path))
        return BetaAnalyticsDataClient()
    except DefaultCredentialsError as e:
        raise AppError(503, "ga_credentials_missing", "No Google credentials found.",
                       hint="Set GOOGLE_APPLICATION_CREDENTIALS to your service-account JSON key.") from e
    except ValueError as e:
        raise AppError(503, "ga_credentials_invalid", "Service-account key file is invalid.", hint=str(e)) from e


class GAService:
    def __init__(
        self,
        property_id: str,
        client: Any | None = None,
        credentials_path: Path | None = None,
        cache: TTLCache | None = None,
        ttl: int = 600,
        realtime_ttl: int = 60,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.property_id = property_id
        self._client = client
        self._client_factory = client_factory
        self.credentials_path = credentials_path
        self.cache = cache or TTLCache()
        self.ttl = ttl
        self.realtime_ttl = realtime_ttl

    # ------------------------------------------------------------ plumbing
    @property
    def client(self) -> Any:
        if not self.property_id:
            raise AppError(503, "ga_not_configured", "No GA4 property selected.",
                           hint="Pick a property, set GA4_PROPERTY_ID in .env, or set MOCK_MODE=true to preview with fake data.")
        if self._client is None:
            self._client = self._client_factory() if self._client_factory else make_data_client(self.credentials_path)
        return self._client

    @property
    def prop(self) -> str:
        return f"properties/{self.property_id}"

    def _call(self, kind: str, fn: Callable[[Any], Any], request: Any, desc: str) -> Any:
        started = time.perf_counter()
        status = "OK"
        try:
            return fn(request)
        except gexc.GoogleAPICallError as e:
            status = type(e).__name__
            raise map_ga_error(e, self.property_id) from e
        except Exception as e:
            status = type(e).__name__
            raise
        finally:
            log.info("GA %s property=%s %s status=%s duration=%.0fms", kind, self.property_id, desc, status,
                     (time.perf_counter() - started) * 1000)

    def _report(
        self,
        dims: list[str],
        metrics: list[str],
        ranges: list[tuple[DateRange, str]],
        limit: int | None = None,
        order_metric: str | None = None,
        order_dim: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = dict(
            property=self.prop,
            dimensions=[Dimension(name=d) for d in dims],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[
                GADateRange(start_date=r.start.isoformat(), end_date=r.end.isoformat(), name=name) for r, name in ranges
            ],
        )
        if limit:
            kwargs["limit"] = limit
        if order_metric:
            kwargs["order_bys"] = [OrderBy(metric=OrderBy.MetricOrderBy(metric_name=order_metric), desc=True)]
        elif order_dim:
            kwargs["order_bys"] = [OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=order_dim))]
        client = self.client
        desc = f"dims={','.join(dims) or '-'} ranges={len(ranges)}"
        return parse_rows(self._call("runReport", client.run_report, RunReportRequest(**kwargs), desc))

    def _realtime(self, dims: list[str], limit: int = 20) -> list[dict[str, Any]]:
        client = self.client
        req = RunRealtimeReportRequest(
            property=self.prop,
            dimensions=[Dimension(name=d) for d in dims],
            metrics=[Metric(name="activeUsers")],
            limit=limit,
        )
        return parse_rows(self._call("runRealtimeReport", client.run_realtime_report, req, f"dims={','.join(dims) or '-'}"))

    def _cached(self, key: tuple, fn: Callable[[], Any], ttl: int | None = None) -> Any:
        return self.cache.get_or_set(("ga", self.property_id, *key), ttl or self.ttl, fn)

    # ------------------------------------------------------------ reports
    def overview(self, r: DateRange) -> GAOverview:
        def load() -> GAOverview:
            prev = r.previous
            rows = self._report([], [m for m, _, _ in OVERVIEW_METRICS], [(r, "current"), (prev, "previous")])
            by_range = {row.get("dateRange", "current"): row for row in rows}
            cur, old = by_range.get("current", {}), by_range.get("previous", {})
            metrics = []
            for key, label, fmt in OVERVIEW_METRICS:
                value, previous = cur.get(key, 0.0), old.get(key)
                metrics.append(KpiMetric(key=key, label=label, value=value, previous=previous,
                                         change_pct=pct_change(value, previous), format=fmt))  # type: ignore[arg-type]
            return GAOverview(range=rng(r), previous_range=rng(prev), metrics=metrics)

        return self._cached(("overview", r.start, r.end), load)

    def timeseries(self, r: DateRange) -> GATimeseries:
        metrics = ["activeUsers", "sessions", "screenPageViews"]

        def series(dr: DateRange) -> list[dict[str, Any]]:
            by_date = {row["date"]: row for row in self._report(["date"], metrics, [(dr, "current")], order_dim="date")}
            out = []
            for d in dr.iter_days():
                row = by_date.get(d.strftime("%Y%m%d"), {})
                out.append({"date": d, **{m: row.get(m, 0.0) for m in metrics}})
            return out

        def load() -> GATimeseries:
            current = series(r)
            points = [TimeseriesPoint(**p) for p in current]
            if r.compare:
                for p, old in zip(points, series(r.previous)):
                    p.prev_date = old["date"]
                    p.prev_activeUsers, p.prev_sessions, p.prev_screenPageViews = (old[m] for m in metrics)
            return GATimeseries(range=rng(r), compare=r.compare, points=points)

        return self._cached(("timeseries", r.start, r.end, r.compare), load)

    def channels(self, r: DateRange) -> GAChannels:
        metrics = ["sessions", "activeUsers", "engagementRate", "keyEvents"]

        def load() -> GAChannels:
            rows = self._report(["sessionDefaultChannelGroup"], metrics, [(r, "current")], order_metric="sessions")
            prev: dict[str, float] = {}
            if r.compare:
                prev = {x["sessionDefaultChannelGroup"]: x["sessions"]
                        for x in self._report(["sessionDefaultChannelGroup"], ["sessions"], [(r.previous, "previous")])}
            out = []
            for x in rows:
                name = x["sessionDefaultChannelGroup"]
                p = prev.get(name) if r.compare else None
                out.append(ChannelRow(channel=name, **{m: x[m] for m in metrics}, prev_sessions=p,
                                      change_pct=pct_change(x["sessions"], p)))
            return GAChannels(range=rng(r), rows=out)

        return self._cached(("channels", r.start, r.end, r.compare), load)

    def sources(self, r: DateRange) -> GASources:
        def load() -> GASources:
            rows = self._report(["sessionSource", "sessionMedium"], ["sessions", "activeUsers", "engagementRate", "keyEvents"],
                                [(r, "current")], limit=100, order_metric="sessions")
            return GASources(range=rng(r), rows=[
                SourceRow(source=x["sessionSource"], medium=x["sessionMedium"], sessions=x["sessions"],
                          activeUsers=x["activeUsers"], engagementRate=x["engagementRate"], keyEvents=x["keyEvents"])
                for x in rows])

        return self._cached(("sources", r.start, r.end), load)

    def pages(self, r: DateRange, limit: int = 50) -> GAPages:
        def load() -> GAPages:
            rows = self._report(["pagePath", "pageTitle"], ["screenPageViews", "activeUsers", "userEngagementDuration"],
                                [(r, "current")], limit=limit, order_metric="screenPageViews")
            return GAPages(range=rng(r), rows=[
                PageRow(pagePath=x["pagePath"], pageTitle=x["pageTitle"], views=x["screenPageViews"], users=x["activeUsers"],
                        avgEngagementTime=round(x["userEngagementDuration"] / x["activeUsers"], 1) if x["activeUsers"] else 0.0)
                for x in rows])

        return self._cached(("pages", r.start, r.end, limit), load)

    def geo(self, r: DateRange) -> GAGeo:
        def load() -> GAGeo:
            countries = self._report(["country"], ["activeUsers", "sessions"], [(r, "current")], limit=50, order_metric="activeUsers")
            cities = self._report(["city", "country"], ["activeUsers"], [(r, "current")], limit=50, order_metric="activeUsers")
            return GAGeo(
                range=rng(r),
                countries=[CountryRow(country=x["country"], activeUsers=x["activeUsers"], sessions=x["sessions"]) for x in countries],
                cities=[CityRow(city=x["city"], country=x["country"], activeUsers=x["activeUsers"]) for x in cities],
            )

        return self._cached(("geo", r.start, r.end), load)

    def tech(self, r: DateRange) -> GATech:
        def by(dim: str, limit: int) -> list[NameCount]:
            rows = self._report([dim], ["activeUsers"], [(r, "current")], limit=limit, order_metric="activeUsers")
            return [NameCount(name=x[dim], value=x["activeUsers"]) for x in rows]

        def load() -> GATech:
            return GATech(range=rng(r), devices=by("deviceCategory", 10), browsers=by("browser", 15),
                          operatingSystems=by("operatingSystem", 15))

        return self._cached(("tech", r.start, r.end), load)

    def events(self, r: DateRange) -> GAEvents:
        def load() -> GAEvents:
            rows = self._report(["eventName"], ["eventCount", "totalUsers"], [(r, "current")], limit=50, order_metric="eventCount")
            return GAEvents(range=rng(r), rows=[EventRow(**x) for x in rows])

        return self._cached(("events", r.start, r.end), load)

    def realtime(self) -> GARealtime:
        def load() -> GARealtime:
            total = self._realtime([], limit=1)

            def by(dim: str) -> list[NameCount]:
                return [NameCount(name=x[dim], value=x["activeUsers"]) for x in self._realtime([dim])]

            return GARealtime(
                activeUsers=total[0]["activeUsers"] if total else 0.0,
                byCountry=by("country"),
                byDevice=by("deviceCategory"),
                byPage=by("unifiedScreenName"),
                fetched_at=datetime.now(timezone.utc),
            )

        return self._cached(("realtime",), load, ttl=self.realtime_ttl)

    def test_connection(self) -> dict[str, Any]:
        """Uncached one-day totals request used by the Settings page."""
        today = datetime.now(get_settings().zone).date()
        r = DateRange(today - timedelta(days=1), today)
        rows = self._report([], ["activeUsers", "sessions"], [(r, "current")])
        row = rows[0] if rows else {}
        return {"activeUsers": row.get("activeUsers", 0.0), "sessions": row.get("sessions", 0.0)}


# One gRPC client and one cache shared by every property; cache keys include the property ID.
_GA_CACHE = TTLCache()


@lru_cache
def _shared_client() -> Any:
    return make_data_client(get_settings().credentials_path())


@lru_cache(maxsize=512)
def get_ga_service(property_id: str) -> GAService:
    """Service bound to one (already validated) property ID."""
    s = get_settings()
    if s.mock_mode:
        from app.services.ga_mock import MockGAService

        return MockGAService(property_id)  # type: ignore[return-value]
    return GAService(property_id, cache=_GA_CACHE, client_factory=_shared_client, ttl=s.ga_cache_ttl_seconds,
                     realtime_ttl=s.ga_realtime_cache_ttl_seconds)
