from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.config import Settings
from app.jobs.clarity_sync import run_sync
from app.models import ClarityApiUsage, ClarityProject, ClarityRawSnapshot, ClaritySyncRun
from app.services.clarity import (
    ClarityAuthError,
    ClarityClient,
    ClarityQuotaExceeded,
    calls_used_today,
    mark_exhausted,
    try_reserve_call,
)
from app.services.clarity_mock import mock_payload

NOW = datetime(2026, 3, 10, 20, 30, tzinfo=timezone.utc)
TODAY = date(2026, 3, 11)  # local date in Asia/Kolkata at NOW


def settings(**kw) -> Settings:
    base = dict(mock_mode=False, clarity_api_token="tok", clarity_safety_limit=9, clarity_daily_limit=10,
                clarity_max_calls_per_run=6, tz="Asia/Kolkata")
    return Settings(**{**base, **kw})


def add_project(db, pid: str = "111", enabled: bool = True) -> ClarityProject:
    p = ClarityProject(ga_property_id=pid, label=f"site {pid}", token_source="db", api_token_encrypted=None, enabled=enabled)
    db.add(p)
    db.commit()
    return p


class FakeFetcher:
    def __init__(self, fail_after: int | None = None, exc: Exception | None = None, pid: str = "") -> None:
        self.calls: list[tuple[int, list[str]]] = []
        self.fail_after = fail_after
        self.exc = exc
        self.pid = pid

    def fetch(self, num_of_days: int, dimensions: list[str]):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            self.calls.append((num_of_days, dimensions))
            raise self.exc or ClarityQuotaExceeded("429")
        self.calls.append((num_of_days, dimensions))
        return mock_payload(TODAY - timedelta(days=1), dimensions, num_of_days, self.pid)


def sync(db, fetchers: dict[str, FakeFetcher] | FakeFetcher, **kw):
    pick = (lambda p: fetchers[p.ga_property_id]) if isinstance(fetchers, dict) else (lambda p: fetchers)
    return run_sync(db, settings(), fetcher_factory=pick, today=kw.pop("today", TODAY), now=kw.pop("now", NOW), **kw)


# ---------------------------------------------------------------- quota guard
def test_reserve_counts_until_safety_limit(db):
    results = [try_reserve_call(db, 1, safety_limit=9, now=NOW) for _ in range(11)]
    assert results == [True] * 9 + [False] * 2
    assert calls_used_today(db, 1, now=NOW) == 9


def test_quota_is_per_project(db):
    for _ in range(9):
        try_reserve_call(db, 1, 9, now=NOW)
    assert not try_reserve_call(db, 1, 9, now=NOW)
    assert try_reserve_call(db, 2, 9, now=NOW)  # another project has its own 10/day
    assert calls_used_today(db, 2, now=NOW) == 1


def test_counter_is_per_utc_day(db):
    for _ in range(9):
        try_reserve_call(db, 1, 9, now=NOW)
    assert not try_reserve_call(db, 1, 9, now=NOW)
    # 04:00 local the next morning is still the same UTC day...
    assert not try_reserve_call(db, 1, 9, now=NOW + timedelta(hours=2))
    # ...but after UTC midnight a new budget starts.
    assert try_reserve_call(db, 1, 9, now=NOW + timedelta(hours=4))


def test_mark_exhausted_blocks_further_calls(db):
    try_reserve_call(db, 1, 9, now=NOW)
    mark_exhausted(db, 1, 10, now=NOW)
    assert not try_reserve_call(db, 1, 9, now=NOW)
    assert calls_used_today(db, 1, now=NOW) == 10
    assert try_reserve_call(db, 2, 9, now=NOW)


# ---------------------------------------------------------------- sync job (single project)
def test_first_run_backfills_then_daily_calls(db):
    p = add_project(db)
    f = FakeFetcher()
    result = sync(db, f)
    assert f.calls[0] == (3, [])
    assert f.calls[1:] == [(1, []), (1, ["URL"]), (1, ["Device"]), (1, ["Source"]), (1, ["Country/Region"])]
    assert len(f.calls) <= 6
    assert result.status == "success" and result.snapshots_stored == 6 and result.calls_made == 6
    assert calls_used_today(db, p.id, now=NOW) == 6
    assert {s.property_id for s in db.query(ClarityRawSnapshot)} == {"111"}
    assert {s.clarity_project_id for s in db.query(ClarityRawSnapshot)} == {p.id}


def test_sync_is_idempotent(db):
    add_project(db)
    sync(db, FakeFetcher())
    f = FakeFetcher()
    result = sync(db, f)
    assert f.calls == []
    assert result.status == "skipped" and len(result.skipped) == 5
    assert db.query(ClarityRawSnapshot).count() == 6


def test_second_day_has_no_backfill(db):
    add_project(db)
    sync(db, FakeFetcher())
    f = FakeFetcher()
    sync(db, f, today=TODAY + timedelta(days=1), now=NOW + timedelta(days=1))
    assert (3, []) not in f.calls and len(f.calls) == 5


def test_quota_guard_stops_sync(db):
    p = add_project(db)
    db.add(ClarityApiUsage(clarity_project_id=p.id, day=NOW.date(), calls=7))
    db.commit()
    f = FakeFetcher()
    result = sync(db, f)
    assert len(f.calls) == 2  # 7 used + 2 = 9 -> guard refuses the rest
    assert result.status == "partial"
    assert any("Quota guard" in e for e in result.errors)


def test_429_marks_quota_exhausted(db):
    p = add_project(db)
    f = FakeFetcher(fail_after=2)
    result = sync(db, f)
    assert result.snapshots_stored == 2 and result.status == "partial"
    assert db.get(ClarityApiUsage, (p.id, NOW.date())).exhausted
    assert db.query(ClaritySyncRun).one().status == "partial"


# ---------------------------------------------------------------- sync job (multiple projects)
def test_each_project_syncs_into_its_own_property(db):
    a, b = add_project(db, "111"), add_project(db, "222")
    fa, fb = FakeFetcher(pid="111"), FakeFetcher(pid="222")
    result = sync(db, {"111": fa, "222": fb})
    assert result.status == "success" and len(result.projects) == 2
    assert len(fa.calls) == len(fb.calls) == 6
    assert calls_used_today(db, a.id, now=NOW) == calls_used_today(db, b.id, now=NOW) == 6
    counts = {pid: db.query(ClarityRawSnapshot).filter_by(property_id=pid).count() for pid in ("111", "222")}
    assert counts == {"111": 6, "222": 6}
    runs = {r.property_id: r.status for r in db.query(ClaritySyncRun)}
    assert runs == {"111": "success", "222": "success"}


def test_one_project_429_does_not_stop_the_others(db):
    a, b, c = add_project(db, "111"), add_project(db, "222"), add_project(db, "333")
    fetchers = {"111": FakeFetcher(fail_after=0), "222": FakeFetcher(fail_after=1, exc=ClarityAuthError("bad token")),
                "333": FakeFetcher(pid="333")}
    result = sync(db, fetchers)
    by = {r.property_id: r for r in result.projects}
    assert by["111"].status == "failed" and db.get(ClarityApiUsage, (a.id, NOW.date())).exhausted
    assert by["222"].status == "partial" and any("bad token" in e for e in by["222"].errors)
    assert by["333"].status == "success" and by["333"].snapshots_stored == 6
    assert result.status == "partial"
    assert not db.get(ClarityApiUsage, (c.id, NOW.date())).exhausted


def test_project_without_token_is_reported_not_fatal(db):
    add_project(db, "111")  # db-sourced but no encrypted token
    add_project(db, "222")
    f = FakeFetcher(pid="222")

    def factory(p):
        if p.ga_property_id == "111":
            from app.jobs.clarity_sync import get_fetcher
            return get_fetcher(settings(), p)  # raises TokenUnavailable
        return f

    result = run_sync(db, settings(), fetcher_factory=factory, today=TODAY, now=NOW)
    by = {r.property_id: r for r in result.projects}
    assert by["111"].status == "failed" and "No API token" in by["111"].errors[0]
    assert by["222"].status == "success"


def test_disabled_and_filtered_projects_are_skipped(db):
    add_project(db, "111", enabled=False)
    add_project(db, "222")
    add_project(db, "333")
    f = FakeFetcher()
    result = run_sync(db, settings(), property_ids={"222"}, fetcher_factory=lambda p: f, today=TODAY, now=NOW)
    assert [r.property_id for r in result.projects] == ["222"]


def test_no_projects(db):
    result = run_sync(db, settings(), fetcher_factory=lambda p: FakeFetcher(), today=TODAY, now=NOW)
    assert result.status == "skipped" and result.projects == []


# ---------------------------------------------------------------- HTTP client
def _client(handler) -> ClarityClient:
    return ClarityClient("secret-token", "https://clarity.test/api", transport=httpx.MockTransport(handler))


def test_client_sends_bearer_and_params():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    assert _client(handler).fetch(1, ["URL", "Device"]) == []
    assert seen["auth"] == "Bearer secret-token"
    assert seen["params"] == {"numOfDays": "1", "dimension1": "URL", "dimension2": "Device"}


def test_client_429_raises_quota_error():
    with pytest.raises(ClarityQuotaExceeded):
        _client(lambda r: httpx.Response(429)).fetch(1, [])


def test_client_validates_arguments():
    with pytest.raises(ValueError):
        _client(lambda r: httpx.Response(200, json=[])).fetch(4, [])
    with pytest.raises(ValueError):
        _client(lambda r: httpx.Response(200, json=[])).fetch(1, ["a", "b", "c", "d"])


def test_client_never_logs_token(caplog):
    caplog.set_level("INFO")
    _client(lambda r: httpx.Response(200, json=[])).fetch(1, [])
    assert "secret-token" not in caplog.text
    assert "status=200" in caplog.text
