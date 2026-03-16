"""Sources API endpoints — list, scan, agentic search with SSE progress."""

from __future__ import annotations

import asyncio
import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse

from emplaiyed.api.app import templates
from emplaiyed.api.deps import get_db, get_profile, get_data_dir
from emplaiyed.core.models import ApplicationStatus, Profile
from emplaiyed.sources import get_available_sources
from emplaiyed.sources.base import SearchQuery

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# List sources (JSON-ish for htmx)
# ---------------------------------------------------------------------------


@router.get("/api/sources/list")
async def list_sources_api():
    """Return available sources as JSON."""
    sources = get_available_sources()
    return [
        {"name": name, "class": type(src).__name__} for name, src in sources.items()
    ]


# ---------------------------------------------------------------------------
# Scan — single source, SSE progress
# ---------------------------------------------------------------------------


@router.post("/api/sources/scan")
async def scan_source(
    request: Request,
    source_name: str = Form(...),
    keywords: str = Form(""),
    location: str = Form(""),
    max_results: int = Form(50),
    profile: Profile | None = Depends(get_profile),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Scan a single source. Returns an SSE stream with progress and results."""
    available = get_available_sources()
    if source_name not in available:
        return HTMLResponse(
            f'<div class="alert alert-error">Unknown source: {source_name}</div>',
            status_code=400,
        )

    # Derive keywords from profile if not provided
    kw_list: list[str] = [k.strip() for k in keywords.split(",") if k.strip()]
    loc = location.strip() or None

    if not kw_list and profile:
        if profile.aspirations and profile.aspirations.target_roles:
            kw_list.extend(profile.aspirations.target_roles)
        if profile.skills:
            kw_list.extend(profile.skills[:5])

    if not kw_list:
        return HTMLResponse(
            '<div class="alert alert-warning">No keywords provided and no profile to derive them from.</div>',
            status_code=400,
        )

    if loc is None and profile and profile.aspirations:
        for pref in profile.aspirations.geographic_preferences:
            if pref.lower().strip() != "remote":
                loc = pref
                break

    source = available[source_name]
    query = SearchQuery(keywords=kw_list, location=loc, max_results=max_results)

    async def event_generator():
        yield {
            "event": "progress",
            "data": f"Scanning {source_name} for: {', '.join(kw_list)}"
            + (f" in {loc}" if loc else "")
            + "...",
        }

        try:
            results = await source.scrape_and_persist(query, conn)
        except NotImplementedError:
            yield {"event": "error", "data": f"{source_name} is not yet implemented."}
            yield {"event": "done", "data": "0"}
            return
        except Exception as exc:
            logger.exception("Scan failed for %s", source_name)
            yield {"event": "error", "data": f"Scan failed: {exc}"}
            yield {"event": "done", "data": "0"}
            return

        if not results:
            yield {"event": "progress", "data": "No new opportunities found."}
            yield {"event": "done", "data": "0"}
            return

        yield {
            "event": "progress",
            "data": f"{len(results)} new opportunities found. Scoring...",
        }

        # Score against profile
        scored_count = 0
        if profile:
            try:
                from emplaiyed.scoring import score_opportunities

                scored = await score_opportunities(profile, results, db_conn=conn)
                scored_count = len(scored)
                above_70 = sum(1 for s in scored if s.score >= 70)
                yield {
                    "event": "progress",
                    "data": f"Scored {scored_count} opportunities. {above_70} scored 70+.",
                }
            except Exception as exc:
                logger.warning("Scoring failed: %s", exc)
                yield {
                    "event": "progress",
                    "data": f"Scoring failed: {exc}. Opportunities saved unscored.",
                }

        yield {
            "event": "done",
            "data": str(len(results)),
        }

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Search — agentic, SSE progress
# ---------------------------------------------------------------------------


@router.post("/api/sources/search")
async def agentic_search_endpoint(
    request: Request,
    direction: str = Form(""),
    time_limit: int = Form(300),
    profile: Profile | None = Depends(get_profile),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Run agentic search across all sources. Returns SSE stream."""
    if not profile:
        return HTMLResponse(
            '<div class="alert alert-warning">Profile required for agentic search. '
            '<a href="/profile/build" class="link">Build one first.</a></div>',
            status_code=400,
        )

    sources = get_available_sources()
    direction_text = direction.strip() or None

    # We use an asyncio.Queue to bridge the sync on_progress callback
    # to the async SSE generator.
    progress_queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _on_progress(msg: str) -> None:
        progress_queue.put_nowait(msg)

    async def _run_search():
        from emplaiyed.sources.search_agent import agentic_search

        try:
            result = await agentic_search(
                profile,
                sources,
                direction=direction_text,
                time_limit=time_limit,
                db_conn=conn,
                on_progress=_on_progress,
            )
            return result
        except Exception as exc:
            logger.exception("Agentic search failed")
            progress_queue.put_nowait(f"ERROR: {exc}")
            return None

    async def event_generator():
        yield {
            "event": "progress",
            "data": "Starting agentic search"
            + (f' with direction: "{direction_text}"' if direction_text else "")
            + f" (time limit: {time_limit // 60}m{time_limit % 60:02d}s)...",
        }

        # Start the search in a background task
        search_task = asyncio.create_task(_run_search())

        # Stream progress events until the search finishes
        while not search_task.done():
            try:
                msg = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                if msg is not None:
                    if msg.startswith("ERROR:"):
                        yield {"event": "error", "data": msg}
                    else:
                        yield {"event": "progress", "data": msg}
            except asyncio.TimeoutError:
                # Just a heartbeat to keep the connection alive
                continue

        # Drain remaining messages
        while not progress_queue.empty():
            msg = progress_queue.get_nowait()
            if msg is not None:
                yield {"event": "progress", "data": msg}

        result = search_task.result()
        if result is None:
            yield {"event": "done", "data": "0"}
            return

        opp_count = len(result.opportunities)
        yield {
            "event": "progress",
            "data": f"Search complete: {opp_count} opportunities found.",
        }

        # Score results
        if profile and result.opportunities:
            yield {"event": "progress", "data": "Scoring opportunities..."}
            try:
                from emplaiyed.scoring import score_opportunities

                scored = await score_opportunities(
                    profile, result.opportunities, db_conn=conn
                )
                above_70 = sum(1 for s in scored if s.score >= 70)
                yield {
                    "event": "progress",
                    "data": f"Scored {len(scored)} opportunities. {above_70} scored 70+.",
                }
            except Exception as exc:
                logger.warning("Scoring failed: %s", exc)
                yield {
                    "event": "progress",
                    "data": f"Scoring failed: {exc}",
                }

        yield {"event": "done", "data": str(opp_count)}

    return EventSourceResponse(event_generator())
