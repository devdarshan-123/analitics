"""Property discovery, validation, per-property GA caching, Clarity project tokens and the DB migration."""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from google.api_core import exceptions as gexc
from sqlalchemy import create_engine, inspect, text

from app.config import Settings
from app.errors import AppError
from app.models import ClarityApiUsage, ClarityMetric, ClarityProject, ClarityRawSnapshot, ClaritySyncRun
from app.services import properties as props_mod
from app.services.clarity_projects import (
    TokenUnavailable,
    adopt_unassigned_rows,
    encrypt_token,
    has_token,
    resolve_token,
    seed_projects,
)
from app.services.ga import GAService
from app.services.properties import GAProperty, PropertyDirectory
from app.utils.dates import DateRange

P = [
    GAProperty("2", "zeta corp", "30", "Main"),
    GAProperty("1", "C:Pesa", "561880898", "C:Pesa"),
    GAProperty("1", "C:Pesa", "560115218", "C Pesa"),
    GAProperty("3", "Acme", "40", "b site"),
    GAProperty("3", "Acme", "41", "A site"),
]


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


# ---------------------------------------------------------------- directory
def test_sorted_by_account_then_property_name():
    d = PropertyDirectory(lambda: P)
    assert [p.property_id for p in d.list()] == ["41", "40", "560115218", "561880898", "30"]


def test_allowlist_filters():
    d = PropertyDirectory(lambda: P, allowlist={"560115218", "30"})
    assert [p.property_id for p in d.list()] == ["560115218", "30"]


def test_allowlist_matching_nothing_explains_why():
    with pytest.raises(AppError) as info:
        PropertyDirectory(lambda: P, allowlist={"1"}).list()
    assert info.value.code == "ga_no_properties" and "ALLOWLIST" in info.value.message


def test_empty_list_gives_access_instructions():
    with pytest.raises(AppError) as info:
        PropertyDirectory(lambda: []).list()
    e = info.value
    assert e.status_code == 503 and e.code == "ga_no_properties"
    assert "Google Analytics Admin API" in e.hint and "ACCOUNT level" in e.hint and "Viewer" in e.hint


def test_cached_for_ttl_and_refresh_bypasses():
    calls = []
    clock = Clock()
    d = PropertyDirectory(lambda: calls.append(1) or P, ttl=3600, clock=clock)
    d.list()
    d.list()
    assert len(calls) == 1
    d.list(refresh=True)
    assert len(calls) == 2
    clock.t = 3601
    d.list()
    assert len(calls) == 3


def test_errors_are_cached_briefly():
    calls = []

    def boom():
        calls.append(1)
        raise AppError(503, "x", "down")

    clock = Clock()
    d = PropertyDirectory(boom, error_ttl=60, clock=clock)
    for _ in range(3):
        with pytest.raises(AppError):
            d.list()
    assert len(calls) == 1
    clock.t = 61
    with pytest.raises(AppError):
        d.list()
    assert len(calls) == 2


def test_default_id():
    d = PropertyDirectory(lambda: P)
    assert d.default_id("") == "41"  # first returned
    assert d.default_id("560115218") == "560115218"
    assert d.default_id("123") == "41"  # configured but not accessible


def test_admin_api_permission_denied_maps_to_setup_hint(monkeypatch, tmp_path):
    key = tmp_path / "sa.json"
    key.write_text(json.dumps({"client_email": "dash@proj.iam.gserviceaccount.com"}))
    client = MagicMock()
    client.list_account_summaries.side_effect = gexc.PermissionDenied("Google Analytics Admin API has not been used")
    from google.analytics.admin_v1beta import AnalyticsAdminServiceClient

    monkeypatch.setattr(AnalyticsAdminServiceClient, "from_service_account_file", classmethod(lambda cls, p: client))
    monkeypatch.setattr(props_mod, "get_settings", lambda: Settings(google_application_credentials=str(key)))
    with pytest.raises(AppError) as info:
        props_mod.fetch_from_admin_api(key)
    e = info.value
    assert e.code == "ga_admin_api_unavailable"
    assert "dash@proj.iam.gserviceaccount.com" in e.hint and "Account access management" in e.hint


def test_admin_api_summaries_are_flattened(monkeypatch, tmp_path):
    key = tmp_path / "sa.json"
    key.write_text("{}")
    summaries = [SimpleNamespace(account="accounts/77", display_name="C:Pesa", property_summaries=[
        SimpleNamespace(property="properties/560115218", display_name="C Pesa"),
        SimpleNamespace(property="properties/561880898", display_name="C:Pesa")])]
    client = MagicMock()
    client.list_account_summaries.return_value = summaries
    from google.analytics.admin_v1beta import AnalyticsAdminServiceClient

    monkeypatch.setattr(AnalyticsAdminServiceClient, "from_service_account_file", classmethod(lambda cls, p: client))
    out = props_mod.fetch_from_admin_api(key)
    assert out == [GAProperty("77", "C:Pesa", "560115218", "C Pesa"), GAProperty("77", "C:Pesa", "561880898", "C:Pesa")]


# ---------------------------------------------------------------- request validation
@pytest.fixture
def directory(monkeypatch):
    def install(fetch, **settings_kw):
        d = PropertyDirectory(fetch)
        s = Settings(**settings_kw)
        monkeypatch.setattr(props_mod, "get_directory", lambda: d)
        monkeypatch.setattr(props_mod, "get_settings", lambda: s)
        return d
    return install


def test_resolve_validates_against_list(directory):
    directory(lambda: P, ga4_property_id="560115218")
    assert props_mod.resolve_property_id(None) == "560115218"
    assert props_mod.resolve_property_id("30") == "30"
    with pytest.raises(AppError) as info:
        props_mod.resolve_property_id("12345")
    assert info.value.status_code == 403 and info.value.code == "property_not_allowed"


def test_resolve_falls_back_to_configured_property_when_discovery_fails(directory):
    def down():
        raise AppError(503, "ga_admin_api_unavailable", "down")

    directory(down, ga4_property_id="560115218")
    assert props_mod.resolve_property_id(None) == "560115218"
    assert props_mod.resolve_property_id("560115218") == "560115218"
    with pytest.raises(AppError) as info:
        props_mod.resolve_property_id("30")  # can't verify anything else
    assert info.value.code == "ga_admin_api_unavailable"


def test_resolve_without_fallback_surfaces_discovery_error(directory):
    directory(lambda: [])
    with pytest.raises(AppError) as info:
        props_mod.resolve_property_id(None)
    assert info.value.code == "ga_no_properties"


# ---------------------------------------------------------------- GA cache isolation
def test_ga_cache_is_keyed_by_property():
    from app.cache import TTLCache

    def resp(value: str):
        return SimpleNamespace(dimension_headers=[SimpleNamespace(name="eventName")],
                               metric_headers=[SimpleNamespace(name="eventCount"), SimpleNamespace(name="totalUsers")],
                               rows=[SimpleNamespace(dimension_values=[SimpleNamespace(value="page_view")],
                                                     metric_values=[SimpleNamespace(value=value), SimpleNamespace(value="1")])])

    shared = TTLCache()
    client = MagicMock()
    client.run_report.side_effect = [resp("10"), resp("20")]
    a = GAService("111", client=client, cache=shared)
    b = GAService("222", client=client, cache=shared)
    r = DateRange(date(2026, 1, 1), date(2026, 1, 2))
    assert a.events(r).rows[0].eventCount == 10
    assert b.events(r).rows[0].eventCount == 20  # not served from 111's cache entry
    assert a.events(r).rows[0].eventCount == 10
    assert client.run_report.call_count == 2
    assert [c.args[0].property for c in client.run_report.call_args_list] == ["properties/111", "properties/222"]


# ---------------------------------------------------------------- tokens & seeding
KEY = Fernet.generate_key().decode()


def test_encrypted_token_roundtrip_and_wrong_key():
    s = Settings(clarity_token_encryption_key=KEY)
    p = ClarityProject(ga_property_id="1", token_source="db", api_token_encrypted=encrypt_token(s, "tok-123"))
    assert "tok-123" not in p.api_token_encrypted
    assert resolve_token(p, s) == "tok-123"
    with pytest.raises(TokenUnavailable, match="changed"):
        resolve_token(p, Settings(clarity_token_encryption_key=Fernet.generate_key().decode()))
    with pytest.raises(TokenUnavailable, match="not set"):
        resolve_token(p, Settings(clarity_token_encryption_key=""))


def test_saving_token_requires_key():
    with pytest.raises(AppError) as info:
        encrypt_token(Settings(clarity_token_encryption_key=""), "tok")
    assert info.value.code == "encryption_key_missing"
    with pytest.raises(AppError) as info:
        encrypt_token(Settings(clarity_token_encryption_key="not-a-key"), "tok")
    assert info.value.code == "encryption_key_invalid"


def test_env_seeding(db):
    s = Settings(mock_mode=False, clarity_api_token="legacy-tok",
                 clarity_tokens='{"560115218": "token-a", "379576149": "token-b"}')
    added = seed_projects(db, s, default_property_id="561880898")
    assert sorted(added) == ["379576149", "560115218", "561880898"]
    rows = {p.ga_property_id: p for p in db.query(ClarityProject)}
    assert all(p.token_source == "env" and p.api_token_encrypted is None for p in rows.values())
    assert resolve_token(rows["560115218"], s) == "token-a"
    assert resolve_token(rows["561880898"], s) == "legacy-tok"  # legacy token -> default property
    assert seed_projects(db, s, "561880898") == []  # idempotent
    assert not has_token(rows["379576149"], Settings())


def test_malformed_clarity_tokens_is_ignored():
    assert Settings(clarity_tokens="{oops").clarity_token_map() == {}
    assert Settings(clarity_tokens='["a"]').clarity_token_map() == {}
    assert Settings(clarity_tokens='{" 1 ": " t "}').clarity_token_map() == {"1": "t"}


# ---------------------------------------------------------------- migration
OLD_SCHEMA = [
    """CREATE TABLE clarity_raw_snapshots (id INTEGER NOT NULL, fetched_at DATETIME NOT NULL, snapshot_date DATE NOT NULL,
       dimensions VARCHAR(200) NOT NULL, num_of_days INTEGER NOT NULL, payload JSON NOT NULL, PRIMARY KEY (id),
       CONSTRAINT uq_snapshot UNIQUE (snapshot_date, dimensions, num_of_days))""",
    "CREATE INDEX ix_clarity_raw_snapshots_snapshot_date ON clarity_raw_snapshots (snapshot_date)",
    """CREATE TABLE clarity_metrics (id INTEGER NOT NULL, snapshot_id INTEGER NOT NULL, snapshot_date DATE NOT NULL,
       num_of_days INTEGER NOT NULL, dimensions VARCHAR(200) NOT NULL, metric_name VARCHAR(100) NOT NULL,
       dimension_key VARCHAR(200) NOT NULL, dimension_value TEXT NOT NULL, field_name VARCHAR(100) NOT NULL,
       value FLOAT NOT NULL, PRIMARY KEY (id), FOREIGN KEY(snapshot_id) REFERENCES clarity_raw_snapshots (id) ON DELETE CASCADE)""",
    "CREATE INDEX ix_metrics_lookup ON clarity_metrics (dimensions, num_of_days, snapshot_date)",
    """CREATE TABLE clarity_api_usage (day DATE NOT NULL, calls INTEGER NOT NULL, exhausted BOOLEAN NOT NULL,
       updated_at DATETIME NOT NULL, PRIMARY KEY (day))""",
    """CREATE TABLE clarity_sync_runs (id INTEGER NOT NULL, started_at DATETIME NOT NULL, finished_at DATETIME,
       "trigger" VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL, calls_made INTEGER NOT NULL,
       snapshots_stored INTEGER NOT NULL, message TEXT NOT NULL, PRIMARY KEY (id))""",
    "INSERT INTO clarity_raw_snapshots VALUES (1, '2026-01-01 02:00:00', '2026-01-01', '', 1, '[]')",
    "INSERT INTO clarity_metrics VALUES (1, 1, '2026-01-01', 1, '', 'Traffic', '', '', 'totalSessionCount', 42)",
    "INSERT INTO clarity_api_usage VALUES ('2026-01-02', 5, 0, '2026-01-02 02:00:00')",
    "INSERT INTO clarity_sync_runs VALUES (1, '2026-01-02 02:00:00', '2026-01-02 02:00:01', 'scheduled', 'success', 5, 5, 'ok')",
]


def test_migration_upgrades_old_database_and_assigns_default_property(tmp_path):
    from sqlalchemy.orm import Session

    from app.db import init_db
    from app.migrate import migrate

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        for sql in OLD_SCHEMA:
            conn.execute(text(sql))
    init_db(engine)
    assert migrate(engine) == []  # idempotent

    insp = inspect(engine)
    assert {"property_id", "clarity_project_id"} <= {c["name"] for c in insp.get_columns("clarity_raw_snapshots")}
    assert insp.get_pk_constraint("clarity_api_usage")["constrained_columns"] == ["clarity_project_id", "day"]
    assert insp.get_foreign_keys("clarity_metrics")[0]["referred_table"] == "clarity_raw_snapshots"

    s = Settings(mock_mode=False, clarity_api_token="legacy")
    with Session(engine) as db:
        seed_projects(db, s, "560115218")
        adopt_unassigned_rows(db, "560115218")
        project = db.query(ClarityProject).one()
        snap = db.query(ClarityRawSnapshot).one()
        assert (snap.property_id, snap.clarity_project_id) == ("560115218", project.id)
        metric = db.query(ClarityMetric).one()
        assert (metric.property_id, metric.clarity_project_id, metric.value) == ("560115218", project.id, 42)
        usage = db.query(ClarityApiUsage).one()
        assert (usage.clarity_project_id, usage.calls) == (project.id, 5)
        assert db.query(ClaritySyncRun).one().property_id == "560115218"

        # A second property can now store the same date/dimension set.
        from app.services.clarity import store_snapshot
        store_snapshot(db, "561880898", date(2026, 1, 1), [], 1, [])
        db.commit()
        assert db.query(ClarityRawSnapshot).count() == 2
