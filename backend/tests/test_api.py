"""End-to-end smoke tests of every endpoint in MOCK_MODE (in-memory DB, mock property list).

Mock properties: 100000001 "Example Store" (Clarity, default), 100000002 "Example Store — Staging"
(no Clarity), 100000003 "Travel Blog" (Clarity).
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_db
from app.jobs.clarity_sync import seed_mock_history
from app.main import app
from app.services.clarity_projects import seed_projects
from app.services.properties import get_directory

GA_ENDPOINTS = ["overview", "timeseries", "channels", "sources", "pages", "geo", "tech", "events", "realtime"]
STORE, STAGING, BLOG = "100000001", "100000002", "100000003"


@pytest.fixture
def client(db) -> Iterator[TestClient]:
    seed_projects(db, get_settings(), STORE)
    seed_mock_history(db, get_settings(), days=10)
    get_directory().clear()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login(c: TestClient) -> None:
    assert c.post("/api/auth/login", json={"password": "test-password"}).status_code == 200


def test_health_is_public(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_routes_require_auth(client):
    for path in ["/api/ga/overview", "/api/clarity/status", "/api/combined/pages", "/api/properties"]:
        r = client.get(path)
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"
    assert client.post("/api/admin/clarity/sync").status_code == 401
    assert client.get("/api/admin/clarity/projects").status_code == 401


def test_wrong_password(client):
    r = client.post("/api/auth/login", json={"password": "nope"})
    assert r.status_code == 401
    assert "dash_session" not in r.cookies


def test_cookie_is_http_only(client):
    r = client.post("/api/auth/login", json={"password": "test-password"})
    assert "httponly" in r.headers["set-cookie"].lower()


# ---------------------------------------------------------------- properties
def test_properties_list_sorted_with_clarity_flags(client):
    login(client)
    props = client.get("/api/properties").json()
    assert [(p["accountName"], p["propertyName"]) for p in props] == [
        ("Example Store", "Example Store"), ("Example Store", "Example Store — Staging"), ("Travel Blog", "Travel Blog")]
    by = {p["propertyId"]: p for p in props}
    assert by[STORE]["hasClarity"] and by[BLOG]["hasClarity"] and not by[STAGING]["hasClarity"]
    assert by[STORE]["accountId"] == "900001"
    # GA4_PROPERTY_ID is unset in tests -> the first property returned is the default
    assert [p["propertyId"] for p in props if p["isDefault"]] == [STORE]
    assert client.get("/api/properties", params={"refresh": "true"}).status_code == 200


@pytest.mark.parametrize("name", GA_ENDPOINTS)
def test_ga_endpoints(client, name):
    login(client)
    r = client.get(f"/api/ga/{name}", params={"start": "2026-01-01", "end": "2026-01-30", "compare": "true",
                                               "propertyId": STORE})
    assert r.status_code == 200, r.text
    assert r.json()


def test_ga_defaults_when_property_missing(client):
    login(client)
    params = {"start": "2026-01-01", "end": "2026-01-30"}
    default = client.get("/api/ga/overview", params=params).json()
    store = client.get("/api/ga/overview", params={**params, "propertyId": STORE}).json()
    assert default == store


def test_properties_return_different_data(client):
    login(client)
    params = {"start": "2026-01-01", "end": "2026-01-30"}
    users = {pid: client.get("/api/ga/overview", params={**params, "propertyId": pid}).json()["metrics"][0]["value"]
             for pid in (STORE, STAGING, BLOG)}
    assert users[STORE] > users[BLOG] > users[STAGING] > 0


def test_unknown_property_is_forbidden(client):
    login(client)
    for path in ["/api/ga/overview", "/api/ga/realtime", "/api/clarity/overview", "/api/clarity/status", "/api/combined/pages"]:
        r = client.get(path, params={"propertyId": "999999999"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "property_not_allowed", path
    assert client.post("/api/admin/test/ga", params={"propertyId": "999999999"}).status_code == 403
    assert client.get("/api/ga/overview", params={"propertyId": "abc"}).status_code == 422


def test_invalid_range(client):
    login(client)
    r = client.get("/api/ga/overview", params={"start": "2026-02-01", "end": "2026-01-01"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_range"


# ---------------------------------------------------------------- Clarity
def test_clarity_endpoints_and_sync(client):
    login(client)
    p = {"propertyId": STORE}
    assert client.get("/api/clarity/overview", params=p).json()["series"]
    fr = client.get("/api/clarity/frustration", params=p).json()
    assert fr["series"] and fr["by_page"]
    pages = client.get("/api/clarity/pages", params=p).json()["rows"]
    assert any(x["path"] == "/pricing" for x in pages)
    assert len({x["path"] for x in pages}) == len(pages)  # query-string variants merged
    for dim in ["Device", "Source", "Country"]:
        assert client.get("/api/clarity/breakdown", params={**p, "dimension": dim}).json()["rows"]
    assert client.get("/api/clarity/breakdown", params={**p, "dimension": "Nope"}).status_code == 422

    before = client.get("/api/clarity/status", params=p).json()
    assert before["linked"] and before["calls_used_today"] == 0 and before["sync_available"]
    result = client.post("/api/admin/clarity/sync", params=p).json()
    assert result["calls_made"] == 5 and result["status"] == "success"
    assert [x["property_id"] for x in result["projects"]] == [STORE]
    again = client.post("/api/admin/clarity/sync", params=p).json()
    assert again["calls_made"] == 0 and again["status"] == "skipped"
    after = client.get("/api/clarity/status", params=p).json()
    assert after["calls_used_today"] == 5 and after["last_successful_sync"]
    # The blog's project has its own quota and wasn't touched
    blog = client.get("/api/clarity/status", params={"propertyId": BLOG}).json()
    assert blog["calls_used_today"] == 0 and blog["last_run"] is None


def test_sync_all_projects(client):
    login(client)
    result = client.post("/api/admin/clarity/sync", params={"all": "true"}).json()
    assert sorted(x["property_id"] for x in result["projects"]) == [STORE, BLOG]
    assert result["calls_made"] == 10


def test_clarity_data_is_isolated_per_property(client):
    login(client)
    store = client.get("/api/clarity/overview", params={"propertyId": STORE}).json()
    blog = client.get("/api/clarity/overview", params={"propertyId": BLOG}).json()
    assert store["kpis"][0]["value"] > blog["kpis"][0]["value"] > 0


def test_property_without_clarity(client):
    login(client)
    p = {"propertyId": STAGING}
    status = client.get("/api/clarity/status", params=p).json()
    assert status["linked"] is False and status["project"] is None and not status["sync_available"]
    for path in ["overview", "frustration", "pages"]:
        r = client.get(f"/api/clarity/{path}", params=p)
        assert r.status_code == 404 and r.json()["error"]["code"] == "clarity_not_linked"
    combined = client.get("/api/combined/pages", params=p).json()
    assert combined["clarity_linked"] is False and combined["rows"]
    assert not any(r["has_clarity"] or r["is_problem"] for r in combined["rows"])
    assert client.post("/api/admin/clarity/sync", params=p).status_code == 404


def test_combined_pages_flags_problems(client):
    login(client)
    data = client.get("/api/combined/pages", params={"propertyId": STORE}).json()
    assert data["clarity_linked"]
    rows = {r["path"]: r for r in data["rows"]}
    assert rows["/pricing"]["has_clarity"] and rows["/pricing"]["scrollDepth"] is not None
    problems = [r for r in data["rows"] if r["is_problem"]]
    assert problems and all(p["problem_reasons"] for p in problems)
    assert "/pricing" in {p["path"] for p in problems}


def test_connection_tests(client):
    login(client)
    assert client.post("/api/admin/test/ga", params={"propertyId": STAGING}).json()["ok"]
    assert client.post("/api/admin/test/clarity", params={"propertyId": STORE}).json()["ok"]
    assert not client.post("/api/admin/test/clarity", params={"propertyId": STAGING}).json()["ok"]


def test_clarity_overview_skips_change_without_comparable_history(client):
    login(client)
    # 10 seeded days: a 30-day range's previous period has no stored history at all.
    kpis = client.get("/api/clarity/overview", params={"propertyId": STORE}).json()["kpis"]
    assert all(k["change_pct"] is None for k in kpis)


# ---------------------------------------------------------------- Clarity project management
def test_link_edit_and_unlink_a_project(client, db):
    login(client)
    created = client.post("/api/admin/clarity/projects", json={"ga_property_id": STAGING, "label": "Staging",
                                                                "api_token": "Bearer  secret-staging-token "})
    assert created.status_code == 200, created.text
    proj = created.json()
    assert proj["token_source"] == "db" and proj["has_token"] and proj["label"] == "Staging"
    assert "secret" not in created.text  # tokens never leave the server

    from app.models import ClarityProject
    row = db.get(ClarityProject, proj["id"])
    assert row.api_token_encrypted and "secret-staging-token" not in row.api_token_encrypted

    from app.services.clarity_projects import resolve_token
    assert resolve_token(row, get_settings()) == "secret-staging-token"

    props = {p["propertyId"]: p for p in client.get("/api/properties").json()}
    assert props[STAGING]["hasClarity"]

    patched = client.patch(f"/api/admin/clarity/projects/{proj['id']}", json={"enabled": False}).json()
    assert patched["enabled"] is False
    assert not {p["propertyId"]: p for p in client.get("/api/properties").json()}[STAGING]["hasClarity"]
    # disabled projects keep their history readable but can't be synced
    assert client.get("/api/clarity/overview", params={"propertyId": STAGING}).status_code == 200
    assert client.post("/api/admin/clarity/sync", params={"propertyId": STAGING}).status_code == 400

    listed = client.get("/api/admin/clarity/projects").json()
    assert {p["ga_property_id"] for p in listed} == {STORE, STAGING, BLOG}

    assert client.delete(f"/api/admin/clarity/projects/{proj['id']}").status_code == 200
    assert client.get("/api/clarity/status", params={"propertyId": STAGING}).json()["linked"] is False


def test_cannot_link_unknown_property(client):
    login(client)
    r = client.post("/api/admin/clarity/projects", json={"ga_property_id": "999999999", "api_token": "x"})
    assert r.status_code == 403
