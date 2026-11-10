"""Site report endpoint in MOCK_MODE."""
from __future__ import annotations

from datetime import date

from app.services.report import fmt_range, market_windows
from app.utils.dates import DateRange
from tests.test_api import STAGING, STORE, client, login  # noqa: F401  (fixture re-export)


def test_report_json_and_html(client):  # noqa: F811
    login(client)
    params = {"start": "2026-01-01", "end": "2026-01-07", "propertyId": STORE, "label": "Last 7 days"}
    data = client.get("/api/report", params=params).json()
    assert data["totals"]["sessions"] > 0 and data["totals_prev"]["sessions"] > 0
    assert data["channels"] and data["pages"] and data["clarity"]["linked"]
    assert data["internal_total"] > 0  # mock hostName includes localhost
    page = client.get("/api/report/html", params=params)
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    body = page.text
    for section in ("Enquiries", "The period in four numbers", "How they arrived", "Where from", "Which story is landing",
                    "How far down the homepage", "Where people struggled", "About these figures", "Inversa"):
        assert section in body, section
    assert "<script>alert" not in body


def test_report_without_clarity_and_auth(client):  # noqa: F811
    assert client.get("/api/report/html").status_code == 401
    login(client)
    body = client.get("/api/report/html", params={"propertyId": STAGING}).text
    assert "No Clarity project is linked" in body
    assert client.get("/api/report", params={"propertyId": "999999999"}).status_code == 403


def test_helpers():
    assert fmt_range(DateRange(date(2026, 11, 3), date(2026, 11, 9))) == "3 Nov to 9 Nov 2026"
    assert dict(market_windows(date(2026, 11, 3), "Asia/Kolkata"))["London"] == "18:30 to 18:29"
