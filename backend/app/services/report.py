"""Site report: one live brief for a date range, built from GA4 (Data API) and stored Clarity snapshots.

GA figures use GA's own metric definitions across all hostnames with no filters, so they match the GA UI for the
same property and date range. Internal traffic is reported alongside, never subtracted.
"""
from __future__ import annotations

import html
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import Settings
from app.services import clarity_queries as cq
from app.services.ga import pct_change
from app.utils.dates import DateRange
from app.utils.paths import normalize_path

TOTAL_METRICS = ["sessions", "activeUsers", "newUsers", "screenPageViews", "userEngagementDuration", "eventCount",
                 "keyEvents", "engagementRate"]
EVENT_DIMS = ["eventName", "dateHourMinute", "city", "country", "sessionSource", "landingPage", "deviceCategory"]
MARKETS = [("London", "Europe/London"), ("Nairobi", "Africa/Nairobi"), ("Singapore", "Asia/Singapore")]
STRUGGLES = {
    "rage": ("Repeated clicks in one spot", "rage clicks"),
    "dead": ("Clicks on something that does nothing", "dead clicks"),
    "quickback": ("Quick backs", "people leaving a page almost immediately after arriving"),
    "excessive_scroll": ("Excessive scrolling", "scrolling up and down looking for something"),
    "error_click": ("Clicks that caused an error", "error clicks"),
    "script_error": ("Script errors", "JavaScript errors in the page"),
}


# ---------------------------------------------------------------- data
def _is_internal(value: str, patterns: list[str]) -> bool:
    v = (value or "").lower()
    return any(p in v for p in patterns)


def _split_ranges(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    by = {r.get("dateRange", "current"): r for r in rows}
    return by.get("current", {}), by.get("previous", {})


def _clarity(db: Session, pid: str | None, r: DateRange) -> dict[str, Any]:
    if not pid:
        return {"linked": False}
    totals = cq._load(db, pid, "", r.start, r.end)
    urls = cq._load(db, pid, "URL", r.start, r.end)
    days = sorted(totals)
    sessions = 0.0
    struggles: dict[str, dict[str, float]] = {k: {"count": 0.0, "sessions": 0.0} for k, _, _ in cq.FRUSTRATION}
    for d in days:
        f = totals[d].get("", {})
        s = cq.pick(f, "Traffic", "totalSessionCount") or 0.0
        sessions += s
        for key, _, metric in cq.FRUSTRATION:
            struggles[key]["count"] += cq.pick(f, metric, "subTotal", "count") or 0.0
            struggles[key]["sessions"] += (cq.pick(f, metric, "sessionsWithMetricPercentage") or 0.0) * s / 100
    # Top page per struggle signal, and homepage scroll depth
    top_page: dict[str, tuple[str, float]] = {}
    home: list[tuple[float, float]] = []
    for d in urls:
        for url, f in urls[d].items():
            path = normalize_path(url)
            s = cq.pick(f, "Traffic", "totalSessionCount") or 0.0
            depth = cq.pick(f, "ScrollDepth", "averageScrollDepth")
            if path == "/" and depth is not None:
                home.append((depth, s or 1.0))
            for key, _, metric in cq.FRUSTRATION:
                c = cq.pick(f, metric, "subTotal", "count") or 0.0
                if c and c > top_page.get(key, ("", 0.0))[1]:
                    top_page[key] = (path, c)
    weight = sum(w for _, w in home)
    return {
        "linked": True,
        "days_with_data": len(days),
        "days_in_range": r.days,
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "latest_stored": cq.latest_snapshot(db, pid),
        "sessions": sessions,
        "scrollDepth": cq._wavg([(_day.scrollDepth, _day.sessions) for _day in
                                 (cq._day(d, totals[d].get("", {})) for d in days)]),
        "home_scroll": sum(v * w for v, w in home) / weight if weight else None,
        "struggles": struggles,
        "top_page": {k: v[0] for k, v in top_page.items()},
    }


def build(ga: Any, db: Session, settings: Settings, property_id: str, clarity_pid: str | None, r: DateRange,
          label: str = "") -> dict[str, Any]:
    cur, prev = (r, "current"), (r.previous, "previous")
    jobs = {
        "totals": lambda: ga.report_rows([], TOTAL_METRICS, [cur, prev]),
        "channels": lambda: ga.report_rows(["sessionDefaultChannelGroup"], ["sessions"], [cur], order_metric="sessions"),
        "countries": lambda: ga.report_rows(["country"], ["sessions"], [cur], limit=25, order_metric="sessions"),
        "pages": lambda: ga.report_rows(["pagePath", "pageTitle"], ["screenPageViews", "activeUsers"], [cur], limit=200,
                                        order_metric="screenPageViews"),
        "traffic": lambda: ga.report_rows(["hostName", "sessionSource"], ["sessions"], [cur], limit=500, order_metric="sessions"),
        "home": lambda: ga.report_rows(["eventName", "pagePath"], ["eventCount"], [cur], limit=1000,
                                       event_names=["page_view", "scroll"]),
        "key_events": lambda: ga.report_rows(EVENT_DIMS, ["keyEvents"], [cur], limit=50, order_metric="keyEvents"),
        "forms": lambda: ga.report_rows(EVENT_DIMS + ["hostName"], ["eventCount"], [cur], limit=50,
                                        order_metric="eventCount", event_names=["form_start", "form_submit"]),
        "realtime": lambda: ga.realtime(),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {k: pool.submit(fn) for k, fn in jobs.items()}
        res = {k: f.result() for k, f in futures.items()}

    patterns = settings.internal_host_patterns
    t_cur, t_prev = _split_ranges(res["totals"])

    internal = defaultdict(float)
    internal_total = 0.0
    for row in res["traffic"]:
        host, src = row.get("hostName", ""), row.get("sessionSource", "")
        if _is_internal(host, patterns):
            internal[host] += row["sessions"]
            internal_total += row["sessions"]
        elif _is_internal(src, patterns):
            internal[f"link from {src}"] += row["sessions"]
            internal_total += row["sessions"]

    pages: dict[str, dict[str, Any]] = {}
    for row in res["pages"]:
        p = pages.setdefault(row["pagePath"], {"path": row["pagePath"], "views": 0.0, "users": 0.0, "title": "", "_tv": -1.0})
        p["views"] += row["screenPageViews"]
        p["users"] = max(p["users"], row["activeUsers"])
        title = row.get("pageTitle", "")
        if title and title != "(not set)" and row["screenPageViews"] > p["_tv"]:
            p["title"], p["_tv"] = title, row["screenPageViews"]
    page_list = sorted(pages.values(), key=lambda p: -p["views"])

    home_views = sum(x["eventCount"] for x in res["home"] if x["pagePath"] == "/" and x["eventName"] == "page_view")
    home_scrolls = sum(x["eventCount"] for x in res["home"] if x["pagePath"] == "/" and x["eventName"] == "scroll")

    key_events = [x for x in res["key_events"] if x.get("keyEvents", 0) > 0]
    forms = [x for x in res["forms"] if not _is_internal(x.get("hostName", ""), patterns)
             and not _is_internal(x.get("sessionSource", ""), patterns)]

    rt = res["realtime"]
    return {
        "property_id": property_id,
        "label": label,
        "range": r,
        "previous": r.previous,
        "generated_at": datetime.now(settings.zone),
        "tz": settings.tz,
        "totals": t_cur,
        "totals_prev": t_prev,
        "channels": res["channels"],
        "countries": res["countries"],
        "pages": page_list,
        "internal": dict(sorted(internal.items(), key=lambda kv: -kv[1])),
        "internal_total": internal_total,
        "home": {"views": home_views, "scrolls": home_scrolls},
        "key_events": key_events,
        "key_event_count": t_cur.get("keyEvents", 0.0),
        "forms": forms,
        "form_count": sum(x["eventCount"] for x in res["forms"]),
        "realtime": {"activeUsers": rt.activeUsers, "pages": [(p.name, p.value) for p in rt.byPage[:4]]},
        "clarity": _clarity(db, clarity_pid, r),
        "clarity_url": (f"https://clarity.microsoft.com/projects/view/{settings.clarity_link_map()[property_id]}"
                        if property_id in settings.clarity_link_map() else "https://clarity.microsoft.com/projects"),
        "ga_url": f"https://analytics.google.com/analytics/web/#/p{property_id}/reports/intelligenthome",
    }


# ---------------------------------------------------------------- rendering helpers
def e(v: Any) -> str:
    return html.escape(str(v), quote=True)


def n(v: float | None) -> str:
    return "0" if not v else f"{v:,.0f}"


def mmss(seconds: float | None) -> str:
    s = int(round(seconds or 0))
    return f"{s // 60}:{s % 60:02d}"


def pct(v: float | None, digits: int = 0) -> str:
    return "–" if v is None else f"{v:.{digits}f}%"


def change(cur: float | None, prev: float | None) -> str:
    c = pct_change(cur, prev)
    if c is None:
        return ""
    cls = "up" if c >= 0 else "down"
    return f' · <span class="{cls}">{"+" if c >= 0 else "−"}{abs(c):.1f}%</span>'


def fmt_date(d: date, year: bool = False) -> str:
    return f"{d.day} {d.strftime('%b')}" + (f" {d.year}" if year else "")


def fmt_range(r: DateRange) -> str:
    if r.start == r.end:
        return fmt_date(r.start, True)
    return f"{fmt_date(r.start)} to {fmt_date(r.end, True)}"


def bars(rows: list[tuple[str, float, bool]]) -> str:
    top = max((v for _, v, _ in rows), default=0) or 1
    out = []
    for name, v, grey in rows:
        w = max(1.5, v / top * 100) if v else 0
        out.append(f'<div class="bar{" grey" if grey else ""}"><div class="row"><span>{e(name)}</span><span>{n(v)}</span></div>'
                   f'<div class="track"><div class="fill" style="width:{w:.1f}%"></div></div></div>')
    return "".join(out)


def top_with_other(rows: list[tuple[str, float]], k: int) -> list[tuple[str, float]]:
    head, tail = rows[:k], rows[k:]
    rest = sum(v for _, v in tail)
    return head + ([("Other", rest)] if rest else [])


def when(dhm: str) -> str:
    try:
        dt = datetime.strptime(dhm, "%Y%m%d%H%M")
    except (TypeError, ValueError):
        return ""
    return f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')} · {dt.strftime('%H:%M')}"


def market_windows(day: date, tz: str) -> list[tuple[str, str]]:
    start = datetime.combine(day, time(0, 0), ZoneInfo(tz))
    out = []
    for name, zone in MARKETS:
        local = start.astimezone(ZoneInfo(zone))
        end = local - timedelta(minutes=1)
        out.append((name, f"{local.strftime('%H:%M')} to {end.strftime('%H:%M')}"))
    return out


# ---------------------------------------------------------------- sections
def _headline(d: dict[str, Any]) -> tuple[str, str]:
    t, p = d["totals"], d["totals_prev"]
    visits, ke = t.get("sessions", 0.0), d["key_event_count"]
    first = f"{n(ke)} enquir{'y' if ke == 1 else 'ies'} from {n(visits)} visits" if ke else f"No enquiries, from {n(visits)} visits"
    share = d["internal_total"] / visits if visits else 0
    if share >= 0.2:
        second = f", and {n(d['internal_total'])} of those visits were our own team."
    else:
        c = pct_change(visits, p.get("sessions"))
        second = "." if c is None else f", {'up' if c >= 0 else 'down'} {abs(c):.0f}% on the previous period."
    lede = []
    ch = [x for x in d["channels"] if x["sessions"]]
    if ch:
        lede.append(f"{ch[0]['sessionDefaultChannelGroup']} brought the most visits ({n(ch[0]['sessions'])}).")
    pg = d["pages"]
    if pg:
        name = "The homepage" if pg[0]["path"] == "/" else pg[0]["path"]
        lede.append(f"{name} was the most viewed page, with {n(pg[0]['views'])} views from {n(pg[0]['users'])} users.")
        if len(pg) > 1:
            lede.append(f"Next was {pg[1]['path']}" + (f", “{pg[1]['title'].split(' | ')[0]}”" if pg[1]["title"] else "") + ".")
    if not visits:
        lede = ["Google Analytics has no data for this range yet. GA usually takes up to a day to process a full day."]
    return first + second, " ".join(lede)


def _enquiries(d: dict[str, Any]) -> str:
    ke, fc = d["key_event_count"], d["form_count"]
    head = f'<div class="sec"><span>Enquiries</span><span>{n(ke)} key events · {n(fc)} form events</span></div>'
    cards = []
    if d["key_events"]:
        rows, kind = d["key_events"][:6], "key"
    else:
        rows, kind = d["forms"][:4], "form"
    for x in rows:
        src = x.get("sessionSource", "")
        cards.append(f'''<div class="enq{'' if kind == 'key' else ' int'}"><div class="top"><h4>{e(x.get('eventName', ''))}, {e(x.get('city') or x.get('country') or '(not set)')}
          <span class="pill">{e(src.upper() or 'UNKNOWN')}</span></h4><span class="t">{e(when(x.get('dateHourMinute', '')))}</span></div>
          <div class="sub">{'Key event' if kind == 'key' else 'Form activity, not a key event'} · {e(x.get('country', ''))}</div>
          <div class="grid"><div><div class="l">Found you via</div><div class="x">{e(src or '(not set)')}</div></div>
          <div><div class="l">Device</div><div class="x">{e((x.get('deviceCategory') or '').capitalize())}</div></div>
          <div><div class="l">Count</div><div class="x">{n(x.get('keyEvents') or x.get('eventCount'))}</div></div>
          <div><div class="l">Landed on</div><div class="x">{e(x.get('landingPage', ''))}</div></div></div></div>''')
    if d["key_events"]:
        note = "Key events as GA records them. GA does not identify people, so names and companies are not available."
    elif rows:
        note = ("No key events were recorded, so no enquiry is being counted. These are the form starts from outside the "
                "team. To count enquiries, mark the enquiry form's submit event as a key event in GA (Admin → Events).")
    else:
        note = ("No key events and no outside form activity in this range. To count enquiries, mark the enquiry form's "
                "submit event as a key event in GA (Admin → Events).")
    return head + "".join(cards) + f'<p class="note">{note}</p>'


def _numbers(d: dict[str, Any]) -> str:
    t, p = d["totals"], d["totals_prev"]
    ratio = lambda a, b: (a / b * 100) if b else None  # noqa: E731
    first, first_p = ratio(t.get("newUsers", 0), t.get("activeUsers", 0)), ratio(p.get("newUsers", 0), p.get("activeUsers", 0))
    read = (t.get("userEngagementDuration", 0) / t["activeUsers"]) if t.get("activeUsers") else 0
    read_p = (p.get("userEngagementDuration", 0) / p["activeUsers"]) if p.get("activeUsers") else 0
    pr = d["previous"]
    return f'''<div class="sec"><span>The period in four numbers</span><span><a href="{e(d['ga_url'])}">vs {e(fmt_range(pr))} ↗</a></span></div>
  <div class="tiles">
    <div class="tile"><div class="k">Visits</div><div class="v">{n(t.get('sessions'))}</div><div class="s">prev {n(p.get('sessions'))}{change(t.get('sessions'), p.get('sessions'))}</div></div>
    <div class="tile"><div class="k">First time here</div><div class="v">{pct(first)}</div><div class="s">prev {pct(first_p)}</div></div>
    <div class="tile"><div class="k">Time reading</div><div class="v">{mmss(read)}</div><div class="s">prev {mmss(read_p)}</div></div>
    <div class="tile"><div class="k">Enquiries</div><div class="v">{n(t.get('keyEvents'))}</div><div class="s">prev {n(p.get('keyEvents'))} key events</div></div>
  </div>
  <p class="note">As shown on GA Home for the same dates: <b>{n(t.get('activeUsers'))} active users</b>{change(t.get('activeUsers'), p.get('activeUsers'))},
  <b>{n(t.get('eventCount'))} events</b>{change(t.get('eventCount'), p.get('eventCount'))} and <b>{n(t.get('keyEvents'))} key events</b>.
  {n(t.get('newUsers'))} new users, {n(t.get('screenPageViews'))} page views. Visits are GA sessions; time reading is average engagement time per active user.</p>'''


def _arrived(d: dict[str, Any]) -> str:
    ch = top_with_other([(x["sessionDefaultChannelGroup"], x["sessions"]) for x in d["channels"]], 5)
    co = top_with_other([(x["country"], x["sessions"]) for x in d["countries"]], 5)
    internal = ""
    if d["internal_total"]:
        parts = ", ".join(f"{n(v)} {k}" for k, v in list(d["internal"].items())[:5])
        internal = (f'<p class="note"><b>{n(d["internal_total"])} of {n(d["totals"].get("sessions"))} visits were internal</b> '
                    f'({e(parts)}). They are included above, exactly as GA counts them.</p>')
    return f'''<div class="two">
    <div><div class="sec"><span>How they arrived</span><span>sessions</span></div>{bars([(a, b, False) for a, b in ch]) or '<p class="note">No data.</p>'}</div>
    <div><div class="sec"><span>Where from</span><span>sessions</span></div>{bars([(a, b, False) for a, b in co]) or '<p class="note">No data.</p>'}</div>
  </div>{internal}'''


def _stories(d: dict[str, Any]) -> str:
    rows = []
    for p in d["pages"][:8]:
        title = p["title"].split(" | ")[0] if p["title"] else ""
        name = ("Homepage" if p["path"] == "/" else p["path"]) + (f" · {title}" if title else "")
        rows.append((name, p["views"], False))
    if not rows:
        return ""
    pg = d["pages"]
    note = f"{'The homepage' if pg[0]['path'] == '/' else pg[0]['path']} reached {n(pg[0]['users'])} users."
    if len(pg) > 1:
        note += f" {pg[1]['path']} had {n(pg[1]['views'])} views from {n(pg[1]['users'])} users."
    return f'''<hr><div class="sec"><span>Which story is landing</span><span>page views</span></div>{bars(rows)}<p class="note">{e(note)}</p>'''


def _scroll(d: dict[str, Any]) -> str:
    h, c = d["home"], d["clarity"]
    if not h["views"]:
        return ""
    reach = h["scrolls"] / h["views"] * 100
    rows = [("Landed", 100.0, f"{n(h['views'])} views")]
    if c.get("home_scroll") is not None:
        rows.append(("Average", c["home_scroll"], "Clarity"))
    rows.append(("Reached 90%", min(reach, 100.0), "GA scroll"))
    html_rows = "".join(f'<div class="scroll"><span class="lab">{e(a)}</span><div class="box"><div class="f" style="width:{v:.0f}%"></div></div>'
                        f'<span class="pc">{v:.0f}%</span><span class="lab" style="font-size:11px">{e(s)}</span></div>' for a, v, s in rows)
    avg = (f" Clarity's average scroll depth on the homepage is {c['home_scroll']:.0f}%." if c.get("home_scroll") is not None else
           " Clarity has no stored homepage data for these dates.")
    return f'''<hr class="brk" style="border:0;margin:0"><div class="sec"><span>How far down the homepage they got</span><span><a href="{e(d['clarity_url'])}/heatmaps">scroll heatmap ↗</a></span></div>{html_rows}
  <p class="note">The homepage had {n(h['views'])} views and {n(h['scrolls'])} of them reached 90% of the page, which is when GA records a scroll.{avg}
  The Clarity scroll heatmap shows the section where people stop.</p>'''


def _struggles(d: dict[str, Any]) -> str:
    c = d["clarity"]
    head = f'<div class="sec"><span>Where people struggled</span><span><a href="{e(d["clarity_url"])}/impressions">from session recordings ↗</a></span></div>'
    if not c.get("linked"):
        return head + '<p class="note">No Clarity project is linked to this property.</p>'
    if not c["days_with_data"]:
        return head + (f'<p class="note">No Clarity data is stored for these dates. Clarity only keeps the last 1 to 3 days and this app '
                       f'stores one snapshot a day; the latest stored day is {e(c["latest_stored"] or "none")}.</p>')
    cards, zero = [], []
    for key, (title, desc) in STRUGGLES.items():
        s = c["struggles"][key]
        if s["count"] > 0:
            where = f" Most on {c['top_page'][key]}." if key in c["top_page"] else ""
            cls = "r" if key in ("rage", "error_click", "script_error") else "a"
            cards.append(f'<div class="issue"><div class="num {cls}">{n(s["count"])}</div><div><h4>{e(title)}</h4>'
                         f'<p>{n(s["count"])} {e(desc)}, in {n(s["sessions"])} of {n(c["sessions"])} sessions.{e(where)}</p></div></div>')
        else:
            zero.append(desc.split(",")[0])
    if zero:
        cards.append(f'<div class="issue"><div class="num g">0</div><div><h4>{"Nothing else" if cards else "No struggle signals"}</h4><p>No {e(", ".join(zero))}.</p></div></div>')
    return head + "".join(cards)


def _one_thing(d: dict[str, Any]) -> str:
    t, c = d["totals"], d["clarity"]
    visits = t.get("sessions", 0.0)
    st = c.get("struggles", {}) if c.get("linked") else {}
    if visits and d["internal_total"] / visits >= 0.2:
        title = "Filter out internal traffic"
        body = (f"{n(d['internal_total'])} of {n(visits)} visits came from internal hosts or links "
                f"({', '.join(list(d['internal'])[:4])}). Until GA has an internal-traffic or hostname filter and Clarity is "
                f"limited to the production domain, every number here overstates real visitors.")
    elif st.get("rage", {}).get("count"):
        title = "Watch the rage-click recordings"
        body = f"There were {n(st['rage']['count'])} rage clicks, most on {c['top_page'].get('rage', 'one page')}. Repeated clicks in one spot usually mean something looks clickable or broken."
    elif st.get("dead", {}).get("count"):
        title = "Check what people are clicking"
        body = f"There were {n(st['dead']['count'])} dead clicks, most on {c['top_page'].get('dead', 'one page')}. Something there looks like a link but isn't."
    elif not d["key_event_count"]:
        title = "Start counting enquiries"
        body = "GA recorded no key events, so enquiries can't be measured. Mark the enquiry form's submit event as a key event in GA (Admin → Events)."
    else:
        return ('<div class="callout green"><h3>Nothing today</h3><p>No struggle signals and no internal-traffic problem. '
                'No decision is waiting on you.</p></div>')
    return f'''<div class="callout"><h3>One thing worth ten minutes today</h3><p><b>{e(title)}.</b> {e(body)}</p>
    <div class="btns"><a class="btn" href="{e(d['clarity_url'])}/impressions">WATCH THE RECORDINGS</a>
    <a class="btn" href="{e(d['clarity_url'])}/heatmaps">OPEN HEATMAPS</a>
    <a class="btn ghost" href="{e(d['ga_url'])}">OPEN GOOGLE ANALYTICS</a></div></div>'''


def _about(d: dict[str, Any]) -> str:
    r, c = d["range"], d["clarity"]
    zones = "".join(f"<span>{e(a)} <b>{e(b)}</b></span>" for a, b in market_windows(r.start, d["tz"]))
    if c.get("linked") and c["days_with_data"]:
        cl = (f"Clarity figures come from {c['days_with_data']} of the {c['days_in_range']} days in this range "
              f"({fmt_date(c['first_day'])} to {fmt_date(c['last_day'])}), from the daily snapshots this app stores. "
              f"Clarity itself only keeps the last 1 to 3 days.")
    else:
        cl = "Clarity only keeps the last 1 to 3 days, and this app has no stored Clarity snapshot for these dates."
    return f'''<div class="sec"><span>About these figures</span><span></span></div><div class="about">
    <p>Everything above covers <b>{e(fmt_range(r))}</b> in <b>{e(d['tz'])}</b> time, the clock the GA property reports on. Each day in other markets:</p>
    <div class="zones">{zones}</div>
    <p class="small">GA numbers are the same as the Google Analytics UI for the same property and dates (all hostnames, no filters).
    GA keeps processing the most recent day for up to 24 to 48 hours, so today's and yesterday's numbers can still rise. {e(cl)}</p></div>'''


def render_html(d: dict[str, Any]) -> str:
    css = (Path(__file__).resolve().parent.parent / "templates" / "report.css").read_text(encoding="utf-8")
    r = d["range"]
    headline, lede = _headline(d)
    rt = d["realtime"]
    label = d["label"] or fmt_range(r)
    title = f"Inversa-Technosoft-Site-Report-{r.start.isoformat()}-to-{r.end.isoformat()}"
    gen = d["generated_at"]
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{css}</style></head><body>
<div class="toolbar"><span>Live report · generated {e(gen.strftime('%d %b %Y, %H:%M'))}</span>
<span><button onclick="window.print()">Download PDF</button><button onclick="location.reload()" class="ghost">Regenerate</button></span></div>
<div class="page">
<div class="state">SITE REPORT · GA PROPERTY {e(d['property_id'])}</div>
<div class="sheet">
  <div class="brand"><div class="logo"><b>Inversa</b> Technosoft<span style="color:#f5ba41">⚡</span></div><div class="tag">SITE REPORT</div></div>
  <div class="daterow"><span>{e(label)} · <b>{e(fmt_range(r))}</b></span><span>Right now <b>{n(rt['activeUsers'])} active</b> · last 30 min</span></div>
  <div class="headline">{e(headline)}</div>
  <p class="lede">{e(lede)}</p>
  <hr>{_enquiries(d)}
  <hr>{_numbers(d)}
  <hr>{_arrived(d)}
  {_stories(d)}
  {_scroll(d)}
  <hr>{_struggles(d)}
  <hr>{_one_thing(d)}
  <hr>{_about(d)}
  <div class="foot"><p>Visits, sources, pages, enquiries and the 90% scroll from Google Analytics (property {e(d['property_id'])}),
  fetched live at {e(gen.strftime('%H:%M %Z, %d %b %Y'))}. Scroll depth and struggle signals from Microsoft Clarity.</p>
  <div class="sig">Prepared by Inversa Technosoft</div></div>
</div></div>
<script>if (location.hash === "#print") setTimeout(() => window.print(), 600);</script>
</body></html>'''
