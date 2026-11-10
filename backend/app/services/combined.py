"""Join GA top pages with Clarity per-URL metrics and flag problem pages."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from app.schemas import ClarityPageRow, CombinedPageRow, CombinedPages, CombinedThresholds, GAPages, RangeInfo
from app.utils.paths import normalize_path


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile; 0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[idx]


def frustration_score(c: ClarityPageRow) -> float:
    """Weighted share of sessions hitting frustration signals; rage clicks count double."""
    return round(2 * (c.rage_pct or 0) + (c.dead_pct or 0) + 0.5 * (c.quickback_pct or 0) + (c.error_click_pct or 0), 2)


def problem_reasons(c: ClarityPageRow) -> list[str]:
    reasons = []
    if (c.rage_pct or 0) >= 3:
        reasons.append(f"Rage clicks in {c.rage_pct:.1f}% of sessions")
    if (c.dead_pct or 0) >= 8:
        reasons.append(f"Dead clicks in {c.dead_pct:.1f}% of sessions")
    if (c.quickback_pct or 0) >= 12:
        reasons.append(f"Quick backs in {c.quickback_pct:.1f}% of sessions")
    if (c.error_click_pct or 0) >= 2:
        reasons.append(f"Error clicks in {c.error_click_pct:.1f}% of sessions")
    if c.scrollDepth is not None and c.scrollDepth < 40:
        reasons.append(f"Low scroll depth ({c.scrollDepth:.0f}%)")
    return reasons


def combine_pages(ga: GAPages, clarity: list[ClarityPageRow], history_start: date | None) -> CombinedPages:
    clarity_by_path = {c.path: c for c in clarity}

    # Several GA rows can share a path (different titles / query strings); merge them.
    merged: dict[str, dict] = defaultdict(lambda: {"views": 0.0, "users": 0.0, "eng_weighted": 0.0, "title": "", "title_views": -1.0})
    for row in ga.rows:
        m = merged[normalize_path(row.pagePath)]
        m["views"] += row.views
        m["users"] += row.users
        m["eng_weighted"] += row.avgEngagementTime * row.users
        if row.views > m["title_views"]:
            m["title"], m["title_views"] = row.pageTitle, row.views

    rows: list[CombinedPageRow] = []
    for path, m in merged.items():
        c = clarity_by_path.get(path)
        base = CombinedPageRow(path=path, pageTitle=m["title"], views=m["views"], users=m["users"],
                               avgEngagementTime=round(m["eng_weighted"] / m["users"], 1) if m["users"] else 0.0,
                               has_clarity=c is not None)
        if c:
            base.clarity_sessions = c.sessions
            base.scrollDepth = c.scrollDepth
            base.dead_pct, base.rage_pct = c.dead_pct, c.rage_pct
            base.quickback_pct, base.error_click_pct = c.quickback_pct, c.error_click_pct
            base.dead_count, base.rage_count = c.dead_count, c.rage_count
            base.frustration_score = frustration_score(c)
        rows.append(base)

    min_views = percentile([r.views for r in rows], 75)
    scores = [r.frustration_score for r in rows if r.frustration_score is not None]
    min_score = max(8.0, percentile(scores, 75))
    for r in rows:
        if r.frustration_score is not None and r.views >= min_views and r.frustration_score >= min_score:
            r.is_problem = True
            c = clarity_by_path[r.path]
            r.problem_reasons = problem_reasons(c) or [f"Frustration score {r.frustration_score:.1f} on a top-traffic page"]

    rows.sort(key=lambda r: -r.views)
    return CombinedPages(range=RangeInfo(start=ga.range.start, end=ga.range.end), clarity_history_start=history_start,
                         thresholds=CombinedThresholds(min_views=min_views, min_frustration_score=min_score), rows=rows)
