"""Application action routes (state transitions, notes, generate, delete)."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime

import json

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse

from emplaiyed.api.deps import get_db, get_profile
from emplaiyed.core.database import (
    delete_application,
    get_application,
    get_opportunity,
    save_interaction,
)
from emplaiyed.core.models import (
    ApplicationStatus,
    Interaction,
    InteractionType,
    Profile,
)
from emplaiyed.generation.pipeline import generate_assets, get_asset_dir, has_assets
from emplaiyed.tracker.state_machine import InvalidTransitionError, transition

router = APIRouter(prefix="/api/applications", tags=["applications"])


# ---------------------------------------------------------------------------
# State transition
# ---------------------------------------------------------------------------


@router.post("/{application_id}/transition")
async def transition_application(
    application_id: str,
    target_status: str = Form(...),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Perform a state transition on an application.

    Called by htmx from the detail page action buttons.
    On success, redirects back to the detail page (htmx re-fetches into main).
    On error, returns an inline error message.
    """
    try:
        target = ApplicationStatus(target_status)
    except ValueError:
        return HTMLResponse(
            f'<div class="alert alert-error">Invalid status: {target_status}</div>',
            status_code=400,
        )

    try:
        transition(conn, application_id, target)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="alert alert-error">{exc}</div>',
            status_code=404,
        )
    except InvalidTransitionError as exc:
        return HTMLResponse(
            f'<div class="alert alert-error">{exc}</div>',
            status_code=422,
        )

    resp = HTMLResponse(status_code=200)
    resp.headers["HX-Redirect"] = f"/applications/{application_id}"
    resp.headers["HX-Trigger"] = json.dumps(
        {
            "showToast": {
                "message": f"Transitioned to {target.value}",
                "level": "success",
            }
        }
    )
    return resp


# ---------------------------------------------------------------------------
# Add note
# ---------------------------------------------------------------------------


@router.post("/{application_id}/notes")
async def add_note(
    application_id: str,
    content: str = Form(...),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Add a note (Interaction of type NOTE) to an application."""
    app = get_application(conn, application_id)
    if app is None:
        return HTMLResponse(
            '<div class="alert alert-error">Application not found</div>',
            status_code=404,
        )

    content = content.strip()
    if not content:
        return HTMLResponse(
            '<div class="alert alert-warning">Note cannot be empty</div>',
            status_code=400,
        )

    save_interaction(
        conn,
        Interaction(
            application_id=application_id,
            type=InteractionType.NOTE,
            direction="internal",
            channel="web",
            content=content,
            created_at=datetime.now(),
        ),
    )

    resp = HTMLResponse(status_code=200)
    resp.headers["HX-Redirect"] = f"/applications/{application_id}"
    resp.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": "Note saved", "level": "success"}}
    )
    return resp


# ---------------------------------------------------------------------------
# Generate assets
# ---------------------------------------------------------------------------


@router.post("/{application_id}/generate")
async def generate_application_assets(
    application_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    profile: Profile | None = Depends(get_profile),
):
    """Generate CV and cover letter for an application.

    This is a potentially long-running operation (LLM calls).
    Returns an HX-Redirect on success so htmx reloads the detail page.
    """
    app = get_application(conn, application_id)
    if app is None:
        return HTMLResponse(
            '<div class="alert alert-error">Application not found</div>',
            status_code=404,
        )

    if profile is None:
        return HTMLResponse(
            '<div class="alert alert-error">No profile found. '
            "Please build your profile first.</div>",
            status_code=400,
        )

    if has_assets(application_id):
        # Already generated — just redirect back
        resp = HTMLResponse(status_code=200)
        resp.headers["HX-Redirect"] = f"/applications/{application_id}"
        return resp

    opp = get_opportunity(conn, app.opportunity_id)
    if opp is None:
        return HTMLResponse(
            '<div class="alert alert-error">Opportunity not found</div>',
            status_code=404,
        )

    try:
        await generate_assets(profile, opp, application_id)
    except Exception as exc:
        return HTMLResponse(
            f'<div class="alert alert-error">Generation failed: {exc}</div>',
            status_code=500,
        )

    resp = HTMLResponse(status_code=200)
    resp.headers["HX-Redirect"] = f"/applications/{application_id}"
    resp.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": "Assets generated successfully", "level": "success"}}
    )
    return resp


# ---------------------------------------------------------------------------
# Delete application
# ---------------------------------------------------------------------------


@router.post("/{application_id}/delete")
async def delete_application_endpoint(
    application_id: str,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Delete an application and its assets from disk."""
    app = get_application(conn, application_id)
    if app is None:
        return HTMLResponse(
            '<div class="alert alert-error">Application not found</div>',
            status_code=404,
        )

    # Remove asset files from disk
    asset_dir = get_asset_dir(application_id)
    if asset_dir.exists():
        shutil.rmtree(asset_dir)

    # Cascading delete from DB
    delete_application(conn, application_id)

    # Redirect to dashboard after deletion
    resp = HTMLResponse(status_code=200)
    resp.headers["HX-Redirect"] = "/queue"
    resp.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": "Application deleted", "level": "success"}}
    )
    return resp
