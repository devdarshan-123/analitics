from __future__ import annotations

from datetime import date

from app.models import ClarityMetric, ClarityRawSnapshot
from app.services.clarity import parse_live_insights, store_snapshot
from app.services.clarity_mock import mock_payload


def _values(result, metric, field):
    return [v for v in result.values if v.metric_name == metric and v.field_name == field]


def test_parses_numeric_strings_and_dimensions(clarity_fixture):
    result = parse_live_insights(clarity_fixture)
    sessions = _values(result, "Traffic", "totalSessionCount")
    assert [v.value for v in sessions] == [9554.0, 120.0]
    assert sessions[0].dimension_key == "URL"
    assert sessions[0].dimension_value == "https://www.example.com/pricing/?ref=nav"
    assert _values(result, "Traffic", "PagesPerSessionPercentage")[1].value == 2.5
    assert _values(result, "RageClickCount", "subTotal")[0].value == 512.0


def test_numeric_looking_dimension_value_stays_a_dimension(clarity_fixture):
    result = parse_live_insights(clarity_fixture)
    (row,) = _values(result, "PageTitle", "sessionsCount")
    assert row.dimension_key == "name"
    assert row.dimension_value == "404"
    assert not _values(result, "PageTitle", "name")


def test_unknown_metrics_and_fields_are_kept_not_dropped(clarity_fixture):
    result = parse_live_insights(clarity_fixture)
    assert "BrandNewMetric" in result.unknown_metrics
    assert "BrandNewMetric.mysteryScore" in result.unknown_fields
    assert _values(result, "BrandNewMetric", "mysteryScore")[0].value == 12.5


def test_malformed_items_produce_warnings_not_crashes(clarity_fixture):
    result = parse_live_insights(clarity_fixture)
    # information as a single object is tolerated
    assert _values(result, "ScriptErrorCount", "subTotal")[0].value == 3.0
    joined = " ".join(result.warnings)
    assert "not an object" in joined
    assert "DeadClickCount" in joined
    assert "nested" in joined


def test_non_list_payloads():
    assert parse_live_insights(None).values == []
    assert parse_live_insights("boom").warnings
    wrapped = parse_live_insights({"data": [{"metricName": "Traffic", "information": [{"totalSessionCount": 5}]}]})
    assert wrapped.values[0].value == 5.0


def test_mock_payload_matches_real_shape(clarity_fixture):
    """The mock generator must produce the same structure the fixture documents."""
    payload = mock_payload(date(2026, 1, 5), ["URL"])
    assert isinstance(payload, list)
    assert all(set(b) == {"metricName", "information"} for b in payload)
    fixture_traffic_fields = set(clarity_fixture[0]["information"][0])
    mock_traffic = next(b for b in payload if b["metricName"] == "Traffic")
    assert set(mock_traffic["information"][0]) == fixture_traffic_fields
    result = parse_live_insights(payload)
    assert not result.unknown_metrics and not result.warnings


def test_store_snapshot_persists_raw_and_normalised(db, clarity_fixture):
    snap, parsed = store_snapshot(db, "123", date(2026, 1, 1), ["URL"], 1, clarity_fixture, project_id=7)
    db.commit()
    assert db.query(ClarityRawSnapshot).one().payload == clarity_fixture
    assert snap.property_id == "123" and snap.clarity_project_id == 7
    assert db.query(ClarityMetric).count() == len(parsed.values) > 0
    assert {(m.dimensions, m.property_id, m.clarity_project_id) for m in db.query(ClarityMetric)} == {("URL", "123", 7)}
