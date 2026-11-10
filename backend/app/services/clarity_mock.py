"""Fake Clarity responses in the real project-live-insights shape, for MOCK_MODE."""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta
from typing import Any

from app.services import mock_data as md
from app.services.ga_mock import _day

log = logging.getLogger("app.clarity")

FRUSTRATION_BASE = {  # metric -> (% of sessions, clicks per affected session)
    "DeadClickCount": (4.5, 2.2),
    "RageClickCount": (1.6, 3.1),
    "QuickbackClick": (6.0, 1.3),
    "ExcessiveScroll": (2.4, 1.0),
    "ErrorClickCount": (0.9, 1.5),
    "ScriptErrorCount": (1.2, 2.4),
}

DIM_VALUES: dict[str, list[tuple[str, float]]] = {
    "Device": [("Mobile", 0.6), ("PC", 0.36), ("Tablet", 0.04)],
    "Source": [("google", 0.42), ("(direct)", 0.25), ("instagram.com", 0.07), ("bing", 0.05), ("facebook.com", 0.05),
               ("newsletter", 0.05), ("chatgpt.com", 0.03), ("t.co", 0.02)],
    "Country/Region": [(c, s) for c, s, _ in md.COUNTRIES],
}


def _block(r: random.Random, sessions: float, dim: dict[str, str], frustration: float, scroll: float) -> dict[str, list[dict]]:
    users = sessions * r.uniform(0.74, 0.86)
    out: dict[str, list[dict]] = {
        "Traffic": [{"totalSessionCount": str(round(sessions)), "totalBotSessionCount": str(round(sessions * r.uniform(0.05, 0.12))),
                     "distantUserCount": str(round(users)), "PagesPerSessionPercentage": round(r.uniform(1.8, 2.9), 2), **dim}],
        "EngagementTime": [{"totalTime": round(r.uniform(150, 330)), "activeTime": round(r.uniform(45, 110)), **dim}],
        "ScrollDepth": [{"averageScrollDepth": round(min(98, max(5, scroll * r.uniform(0.88, 1.12))), 2), **dim}],
    }
    for metric, (pct, per) in FRUSTRATION_BASE.items():
        p = min(60.0, pct * frustration * r.uniform(0.75, 1.25))
        affected = sessions * p / 100
        out[metric] = [{
            "sessionsCount": str(round(sessions)),
            "sessionsWithMetricPercentage": round(p, 2),
            "sessionsWithoutMetricPercentage": round(100 - p, 2),
            "pagesViews": str(round(sessions * 2.3)),
            "subTotal": str(round(affected * per)),
            **dim,
        }]
    return out


def mock_payload(day: date, dimensions: list[str], num_of_days: int = 1, property_id: str = "") -> list[dict[str, Any]]:
    r = random.Random(f"{property_id}|{day.isoformat()}|{'|'.join(dimensions)}|{num_of_days}")
    sessions = sum(_day(day - timedelta(days=i), property_id)["sessions"] for i in range(num_of_days)) * 0.88
    merged: dict[str, list[dict]] = {}

    def add(blocks: dict[str, list[dict]]) -> None:
        for k, rows in blocks.items():
            merged.setdefault(k, []).extend(rows)

    dim = dimensions[0] if dimensions else None
    if dim is None:
        add(_block(r, sessions, {}, 1.0, 54))
        # Summary metrics that Clarity returns as name/count lists.
        merged["PopularPages"] = [{"url": md.MOCK_DOMAIN + p.path, "visitsCount": str(round(sessions * 2.3 * p.weight))}
                                  for p in md.MOCK_PAGES[:10]]
        merged["Referrer"] = [{"name": n, "sessionsCount": str(round(sessions * s))} for n, s in DIM_VALUES["Source"][:6]]
        merged["Browser"] = [{"name": n, "sessionsCount": str(round(sessions * s))} for n, s in md.BROWSERS]
        merged["Device"] = [{"name": n, "sessionsCount": str(round(sessions * s))} for n, s in DIM_VALUES["Device"]]
        merged["OS"] = [{"name": n, "sessionsCount": str(round(sessions * s))} for n, s in md.OSES]
        merged["Country"] = [{"name": n, "sessionsCount": str(round(sessions * s))} for n, s, _ in md.COUNTRIES[:8]]
    elif dim == "URL":
        for p in md.MOCK_PAGES:
            url = md.MOCK_DOMAIN + p.path + ("/" if p.path != "/" and r.random() < 0.3 else "")
            share = p.weight * r.uniform(0.85, 1.15)
            if p.path == "/pricing":  # a query-string variant that should merge into /pricing
                add(_block(r, sessions * share * 0.15, {"URL": url + "?ref=nav"}, p.frustration, p.scroll))
                share *= 0.85
            add(_block(r, sessions * share, {"URL": url}, p.frustration, p.scroll))
    else:
        for value, share in DIM_VALUES.get(dim, [("Other", 1.0)]):
            frustration = 1.3 if value == "Mobile" else 1.0
            add(_block(r, sessions * share * r.uniform(0.9, 1.1), {dim: value}, frustration, 50 + r.uniform(-8, 12)))
    return [{"metricName": k, "information": v} for k, v in merged.items()]


class MockClarityClient:
    """Mimics ClarityClient.fetch; data describes the last `num_of_days` days ending yesterday."""

    def __init__(self, tz: Any, property_id: str = "") -> None:
        self.tz = tz
        self.property_id = property_id

    def fetch(self, num_of_days: int, dimensions: list[str]) -> Any:
        day = datetime.now(self.tz).date() - timedelta(days=1)
        log.info("Clarity GET (mock) property=%s params=numOfDays=%s dims=%s status=200 duration=0ms", self.property_id,
                 num_of_days, dimensions)
        return mock_payload(day, dimensions, num_of_days, self.property_id)
