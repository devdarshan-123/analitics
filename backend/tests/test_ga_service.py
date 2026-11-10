from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gexc

from app.errors import AppError
from app.services.ga import GAService
from app.utils.dates import DateRange


def response(dims: list[str], metrics: list[str], rows: list[tuple[list[str], list[str]]]):
    """Build an object shaped like a RunReportResponse."""
    return SimpleNamespace(
        dimension_headers=[SimpleNamespace(name=d) for d in dims],
        metric_headers=[SimpleNamespace(name=m) for m in metrics],
        rows=[SimpleNamespace(dimension_values=[SimpleNamespace(value=v) for v in dv],
                              metric_values=[SimpleNamespace(value=v) for v in mv]) for dv, mv in rows],
    )


R = DateRange(date(2026, 1, 1), date(2026, 1, 3))


def service(client) -> GAService:
    return GAService("123", client=client)


def test_overview_computes_change_vs_previous_period():
    metrics = ["activeUsers", "newUsers", "sessions", "screenPageViews", "averageSessionDuration", "engagementRate",
               "bounceRate", "keyEvents"]
    client = MagicMock()
    client.run_report.return_value = response(["dateRange"], metrics, [
        (["current"], ["150", "90", "200", "500", "120.5", "0.6", "0.4", "10"]),
        (["previous"], ["100", "60", "200", "400", "100", "0.5", "0.5", "0"]),
    ])
    ov = service(client).overview(R)
    by = {m.key: m for m in ov.metrics}
    assert by["activeUsers"].value == 150 and by["activeUsers"].change_pct == 50.0
    assert by["sessions"].change_pct == 0.0
    assert by["keyEvents"].change_pct is None  # previous 0 -> undefined
    assert by["engagementRate"].format == "percent"
    req = client.run_report.call_args.args[0]
    assert req.property == "properties/123"
    assert [d.name for d in req.date_ranges] == ["current", "previous"]
    assert req.date_ranges[1].start_date == "2025-12-29" and req.date_ranges[1].end_date == "2025-12-31"
    assert ov.previous_range.start == date(2025, 12, 29)


def test_timeseries_fills_missing_days_and_compares():
    client = MagicMock()
    client.run_report.side_effect = [
        response(["date"], ["activeUsers", "sessions", "screenPageViews"], [(["20260101"], ["5", "6", "7"]), (["20260103"], ["1", "2", "3"])]),
        response(["date"], ["activeUsers", "sessions", "screenPageViews"], [(["20251229"], ["9", "9", "9"])]),
    ]
    ts = service(client).timeseries(DateRange(R.start, R.end, compare=True))
    assert [p.sessions for p in ts.points] == [6, 0, 2]
    assert ts.points[0].prev_sessions == 9 and ts.points[1].prev_sessions == 0
    assert ts.points[0].prev_date == date(2025, 12, 29)


def test_pages_avg_engagement_and_cache():
    client = MagicMock()
    client.run_report.return_value = response(["pagePath", "pageTitle"], ["screenPageViews", "activeUsers", "userEngagementDuration"],
                                              [(["/a", "A"], ["100", "40", "2000"]), (["/b", "B"], ["10", "0", "0"])])
    svc = service(client)
    pages = svc.pages(R)
    assert pages.rows[0].avgEngagementTime == 50.0 and pages.rows[1].avgEngagementTime == 0.0
    svc.pages(R)
    assert client.run_report.call_count == 1  # second call served from cache
    req = client.run_report.call_args.args[0]
    assert req.limit == 50 and req.order_bys[0].metric.metric_name == "screenPageViews"


def test_realtime_report():
    client = MagicMock()
    client.run_realtime_report.side_effect = [
        response([], ["activeUsers"], [([], ["42"])]),
        response(["country"], ["activeUsers"], [(["India"], ["30"])]),
        response(["deviceCategory"], ["activeUsers"], [(["mobile"], ["25"])]),
        response(["unifiedScreenName"], ["activeUsers"], [(["Home"], ["12"])]),
    ]
    rt = service(client).realtime()
    assert rt.activeUsers == 42 and rt.byCountry[0].name == "India" and rt.byPage[0].value == 12


@pytest.mark.parametrize("exc,status,code", [
    (gexc.PermissionDenied("nope"), 403, "ga_permission_denied"),
    (gexc.ResourceExhausted("quota"), 429, "ga_quota_exceeded"),
    (gexc.InvalidArgument("bad"), 400, "ga_invalid_request"),
    (gexc.NotFound("missing"), 404, "ga_property_not_found"),
])
def test_errors_map_to_clear_messages(exc, status, code):
    client = MagicMock()
    client.run_report.side_effect = exc
    with pytest.raises(AppError) as info:
        service(client).events(R)
    assert info.value.status_code == status and info.value.code == code
    if code == "ga_permission_denied":
        assert "Viewer" in info.value.message


def test_missing_property_id():
    with pytest.raises(AppError) as info:
        GAService("").overview(R)
    assert info.value.code == "ga_not_configured"
