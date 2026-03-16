"""API routes for contact extraction and follow-up drafting."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from emplaiyed.api.deps import get_db, get_profile
from emplaiyed.core.database import (
    get_application,
    get_contacts_for_opportunity,
    get_opportunity,
)
from emplaiyed.core.models import Profile

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


@router.get("/{opportunity_id}")
def list_contacts(
    opportunity_id: str,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Get all contacts for an opportunity."""
    contacts = get_contacts_for_opportunity(conn, opportunity_id)
    return [c.model_dump() for c in contacts]


@router.post("/{opportunity_id}/extract")
async def extract_contacts(
    opportunity_id: str,
    force: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Extract contacts from an opportunity's description."""
    from emplaiyed.contacts.extractor import extract_and_save_contacts

    opp = get_opportunity(conn, opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    contacts = await extract_and_save_contacts(conn, opp, force=force)
    return [c.model_dump() for c in contacts]


@router.post("/{opportunity_id}/extract/html", response_class=HTMLResponse)
async def extract_contacts_html(
    opportunity_id: str,
    force: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Extract contacts and return an HTML badge for htmx."""
    from emplaiyed.contacts.extractor import extract_and_save_contacts

    opp = get_opportunity(conn, opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    contacts = await extract_and_save_contacts(conn, opp, force=force)
    if contacts:
        c = contacts[0]
        label = c.name or c.email or "Contact found"
        return HTMLResponse(
            f'<span class="badge badge-sm badge-success badge-outline">{label}</span>'
        )
    return HTMLResponse('<span class="text-xs opacity-50">No contact found</span>')


@router.post("/draft-followup/{application_id}")
async def draft_followup(
    application_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    profile: Profile | None = Depends(get_profile),
):
    """Generate a follow-up draft for an application, targeted at the best contact."""
    from emplaiyed.contacts.followup_drafter import draft_contact_followup

    if not profile:
        raise HTTPException(status_code=400, detail="No profile found")

    app = get_application(conn, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    opp = get_opportunity(conn, app.opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    # Get best contact (highest confidence)
    contacts = get_contacts_for_opportunity(conn, opp.id)
    contact = contacts[0] if contacts else None

    # Determine follow-up number from current status
    followup_number = 1
    if app.status.value in ("FOLLOW_UP_1",):
        followup_number = 2

    days_since = (datetime.now() - app.updated_at).days

    draft = await draft_contact_followup(
        profile,
        opp,
        app,
        contact,
        followup_number=followup_number,
        days_since=max(days_since, 1),
    )

    return {
        "draft": draft.model_dump(),
        "contact": contact.model_dump() if contact else None,
    }
