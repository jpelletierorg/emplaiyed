"""Work item action routes (complete, skip)."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from emplaiyed.api.deps import get_db
from emplaiyed.work.queue import complete_work_item, skip_work_item

router = APIRouter(prefix="/api/work-items", tags=["work-items"])


@router.post("/{work_item_id}/complete")
async def complete_work_item_endpoint(
    work_item_id: str,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Mark a work item as done, record the interaction, and advance the app.

    Called by htmx from the work queue page.
    On success, redirects back to the work queue.
    """
    try:
        complete_work_item(conn, work_item_id)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="alert alert-error">{exc}</div>',
            status_code=400,
        )

    resp = HTMLResponse(status_code=200)
    resp.headers["HX-Redirect"] = "/work"
    resp.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": "Work item completed", "level": "success"}}
    )
    return resp


@router.post("/{work_item_id}/skip")
async def skip_work_item_endpoint(
    work_item_id: str,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Skip a work item and revert the application to its previous state.

    Called by htmx from the work queue page.
    On success, redirects back to the work queue.
    """
    try:
        skip_work_item(conn, work_item_id)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="alert alert-error">{exc}</div>',
            status_code=400,
        )

    resp = HTMLResponse(status_code=200)
    resp.headers["HX-Redirect"] = "/work"
    resp.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": "Work item skipped", "level": "info"}}
    )
    return resp
