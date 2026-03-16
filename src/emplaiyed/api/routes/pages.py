"""Server-rendered HTML pages (htmx-friendly)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from emplaiyed.api.app import templates
from emplaiyed.api.deps import get_db, get_profile
from emplaiyed.console.funnel_stats import compute_funnel
from emplaiyed.console.stages import STAGE_GROUPS
from fastapi.responses import HTMLResponse

from emplaiyed.core.database import (
    get_application,
    list_applications,
    list_applications_by_statuses,
    list_pending_work_items,
    list_status_transitions,
    list_interactions,
    list_events,
    list_offers,
    list_upcoming_events,
    list_work_items,
    get_opportunity,
)
from emplaiyed.core.models import ApplicationStatus, Profile

router = APIRouter()


# ---------------------------------------------------------------------------
# Navigation items (shared across all pages)
# ---------------------------------------------------------------------------

NAV_ITEMS = [
    {"name": "Dashboard", "href": "/", "icon": "chart-bar"},
    {"name": "Queue", "href": "/queue", "icon": "inbox"},
    {"name": "Applied", "href": "/applied", "icon": "paper-airplane"},
    {"name": "Active", "href": "/active", "icon": "phone"},
    {"name": "Offers", "href": "/offers", "icon": "gift"},
    {"name": "Closed", "href": "/closed", "icon": "archive-box"},
    {"name": "Work", "href": "/work", "icon": "clipboard-document-list"},
    {"name": "Profile", "href": "/profile", "icon": "user"},
    {"name": "Sources", "href": "/sources", "icon": "magnifying-glass"},
    {"name": "Calendar", "href": "/calendar", "icon": "calendar"},
]

QUEUE_STATUSES = [
    ApplicationStatus.SCORED,
    ApplicationStatus.OUTREACH_PENDING,
    ApplicationStatus.FOLLOW_UP_PENDING,
]


def _base_context(request: Request, active_page: str) -> dict:
    """Return the template context shared by all pages."""
    return {
        "request": request,
        "nav_items": NAV_ITEMS,
        "active_page": active_page,
    }


def _enrich_applications(conn: sqlite3.Connection, applications: list) -> list[dict]:
    """Attach opportunity and contact data to each application for display."""
    from emplaiyed.core.database import get_contacts_for_opportunity

    enriched = []
    for app in applications:
        opp = get_opportunity(conn, app.opportunity_id)
        contacts = get_contacts_for_opportunity(conn, opp.id) if opp else []
        enriched.append(
            {
                "app": app,
                "opp": opp,
                "contact": contacts[0] if contacts else None,
            }
        )
    return enriched


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@router.get("/")
async def dashboard(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    apps = list_applications(conn)

    # Gather all transitions for funnel computation
    all_transitions = []
    for app in apps:
        all_transitions.extend(list_status_transitions(conn, app.id))

    funnel = compute_funnel(apps, all_transitions)

    # Counts per stage for nav badges
    queue_count = sum(1 for a in apps if a.status in QUEUE_STATUSES)

    ctx = _base_context(request, "Dashboard")
    ctx.update(
        {
            "funnel": funnel,
            "total_apps": len(apps),
            "queue_count": queue_count,
        }
    )
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/queue")
async def queue_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    apps = list_applications_by_statuses(conn, QUEUE_STATUSES)
    enriched = _enrich_applications(conn, apps)
    ctx = _base_context(request, "Queue")
    ctx["applications"] = enriched
    return templates.TemplateResponse("queue.html", ctx)


@router.get("/applied")
async def applied_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    apps = list_applications_by_statuses(conn, STAGE_GROUPS["Applied"])
    enriched = _enrich_applications(conn, apps)
    ctx = _base_context(request, "Applied")
    ctx["applications"] = enriched
    return templates.TemplateResponse("applied.html", ctx)


@router.get("/active")
async def active_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    apps = list_applications_by_statuses(conn, STAGE_GROUPS["Active"])
    enriched = _enrich_applications(conn, apps)
    ctx = _base_context(request, "Active")
    ctx["applications"] = enriched
    return templates.TemplateResponse("active.html", ctx)


@router.get("/offers")
async def offers_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    apps = list_applications_by_statuses(conn, STAGE_GROUPS["Offers"])
    enriched = _enrich_applications(conn, apps)
    ctx = _base_context(request, "Offers")
    ctx["applications"] = enriched
    return templates.TemplateResponse("offers.html", ctx)


@router.get("/closed")
async def closed_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    apps = list_applications_by_statuses(conn, STAGE_GROUPS["Closed"])
    enriched = _enrich_applications(conn, apps)
    ctx = _base_context(request, "Closed")
    ctx["applications"] = enriched
    return templates.TemplateResponse("closed.html", ctx)


@router.get("/work")
async def work_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    pending = list_pending_work_items(conn)

    # Enrich each work item with its application + opportunity
    enriched: list[dict] = []
    for wi in pending:
        app = get_application(conn, wi.application_id)
        opp = get_opportunity(conn, app.opportunity_id) if app else None
        enriched.append({"wi": wi, "app": app, "opp": opp})

    ctx = _base_context(request, "Work")
    ctx["work_items"] = enriched
    return templates.TemplateResponse("work.html", ctx)


@router.get("/profile")
async def profile_page(
    request: Request,
    profile: Profile | None = Depends(get_profile),
):
    ctx = _base_context(request, "Profile")
    ctx["profile"] = profile
    return templates.TemplateResponse("profile.html", ctx)


@router.get("/sources")
async def sources_page(
    request: Request,
    profile: Profile | None = Depends(get_profile),
):
    from emplaiyed.sources import get_available_sources

    sources = get_available_sources()
    source_list = [
        {"name": name, "class_name": type(src).__name__}
        for name, src in sources.items()
        if name != "manual"  # Don't show manual source in scan list
    ]

    # Derive default keywords/location from profile for scan form defaults
    default_keywords = ""
    default_location = ""
    if profile:
        kw_parts: list[str] = []
        if profile.aspirations and profile.aspirations.target_roles:
            kw_parts.extend(profile.aspirations.target_roles)
        if profile.skills:
            kw_parts.extend(profile.skills[:5])
        default_keywords = ", ".join(kw_parts)

        if profile.aspirations:
            for pref in profile.aspirations.geographic_preferences:
                if pref.lower().strip() != "remote":
                    default_location = pref
                    break

    ctx = _base_context(request, "Sources")
    ctx.update(
        {
            "sources": source_list,
            "has_profile": profile is not None,
            "default_keywords": default_keywords,
            "default_location": default_location,
        }
    )
    return templates.TemplateResponse("sources.html", ctx)


@router.get("/applications/{application_id}")
async def application_detail(
    request: Request,
    application_id: str,
    conn: sqlite3.Connection = Depends(get_db),
):
    app = get_application(conn, application_id)
    if app is None:
        return HTMLResponse(
            "<h1>Application not found</h1>",
            status_code=404,
        )

    opp = get_opportunity(conn, app.opportunity_id)
    transitions = list_status_transitions(conn, app.id)
    interactions = list_interactions(conn, app.id)
    events = list_events(conn, application_id=app.id)
    offers = list_offers(conn, application_id=app.id)
    work_items = list_work_items(conn, application_id=app.id)

    # Check for generated assets
    from emplaiyed.generation.pipeline import has_assets

    assets_ready = has_assets(app.id)

    # Build unified timeline (transitions + interactions + events)
    timeline: list[dict] = []
    for t in transitions:
        timeline.append(
            {
                "timestamp": t.transitioned_at,
                "type": "transition",
                "label": f"{t.from_status} \u2192 {t.to_status}",
                "detail": None,
            }
        )
    for i in interactions:
        timeline.append(
            {
                "timestamp": i.created_at,
                "type": "interaction",
                "label": f"[{i.type.value}]",
                "detail": (i.content or "")[:200],
            }
        )
    for e in events:
        timeline.append(
            {
                "timestamp": e.scheduled_date,
                "type": "event",
                "label": f"[EVENT] {e.event_type}",
                "detail": e.notes,
            }
        )
    timeline.sort(key=lambda x: x["timestamp"])

    # Valid next transitions
    from emplaiyed.tracker.state_machine import VALID_TRANSITIONS

    next_statuses = VALID_TRANSITIONS.get(app.status, set())

    ctx = _base_context(request, "")
    ctx.update(
        {
            "app": app,
            "opp": opp,
            "transitions": transitions,
            "interactions": interactions,
            "events": events,
            "offers": offers,
            "work_items": work_items,
            "timeline": timeline,
            "assets_ready": assets_ready,
            "next_statuses": sorted(next_statuses, key=lambda s: s.value),
        }
    )
    return templates.TemplateResponse("application_detail.html", ctx)


@router.get("/calendar")
async def calendar_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    upcoming = list_upcoming_events(conn)

    # Enrich each event with its application + opportunity
    enriched: list[dict] = []
    for ev in upcoming:
        app = get_application(conn, ev.application_id)
        opp = get_opportunity(conn, app.opportunity_id) if app else None
        enriched.append({"event": ev, "app": app, "opp": opp})

    ctx = _base_context(request, "Calendar")
    ctx["events"] = enriched
    return templates.TemplateResponse("calendar.html", ctx)
