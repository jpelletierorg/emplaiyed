"""Agentic job search — a Pydantic AI agent that autonomously finds jobs.

The agent reasons about the user's profile, generates diverse search queries
across available sources, adapts based on results, and stops when time is up
or it has enough relevant opportunities.

Opportunities are persisted to the database as they are found, so even if the
agent is interrupted, all discovered jobs are already saved.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from emplaiyed.core.models import Opportunity, Profile
from emplaiyed.sources.base import BaseSource, SearchQuery
from emplaiyed.sources.location_filter import filter_by_location

logger = logging.getLogger(__name__)

from emplaiyed.llm.config import SEARCH_MODEL

DEFAULT_TIME_LIMIT = 300  # 5 minutes


@dataclass
class SearchDeps:
    """Runtime dependencies injected into the agent."""

    profile: Profile
    sources: dict[str, BaseSource]
    start_time: float = field(default_factory=time.monotonic)
    time_limit: float = DEFAULT_TIME_LIMIT
    found: list[Opportunity] = field(default_factory=list)
    seen_keys: set[tuple[str, str, str]] = field(default_factory=set)
    queries_tried: list[str] = field(default_factory=list)
    db_conn: sqlite3.Connection | None = None
    on_progress: Callable[[str], None] | None = None
    _model_override: Model | None = None


class SearchResult(BaseModel):
    """Final output the agent must produce."""

    opportunities: list[Opportunity] = Field(default_factory=list)
    queries_used: list[str] = Field(default_factory=list)
    summary: str = ""


search_agent = Agent(
    deps_type=SearchDeps,
    output_type=SearchResult,
    instructions=(
        "You are a job search agent. Your goal is to find relevant job "
        "opportunities for the user by searching multiple job sources with "
        "diverse queries.\n\n"
        "Strategy:\n"
        "1. Start by analyzing the user's profile AND the user direction "
        "(if provided). The direction may contain EXCLUSION criteria "
        "(e.g. 'not in banking') — respect these strictly.\n"
        "2. Generate 3-5 diverse search queries covering: exact target roles, "
        "related roles, skill-based queries, and industry-based queries.\n"
        "3. ALWAYS pass the `location` parameter when calling search_jobs. Use the "
        "candidate's preferred locations from their profile. Cycle through the "
        "preferred locations across your search calls (e.g., first call uses "
        "'Montreal', next uses 'Longueuil', etc.). NEVER call search_jobs without "
        "a location parameter.\n"
        "4. Call search_jobs for each query. After each call, REVIEW the results "
        "against the user's criteria.\n"
        "5. Call reject_opportunities to remove any results that violate the "
        "user's direction (wrong industry, wrong role type, etc.).\n"
        "6. If a query returns few results (<3), try a broader or alternative query.\n"
        "7. If you get many duplicates, switch to a completely different angle.\n"
        "8. Try queries in both English and French (the user is in Quebec).\n"
        "9. The tool will tell you how much time is left. When time is almost up, "
        "stop searching and return your results.\n"
        "10. Return ALL kept opportunities with a summary of your search strategy.\n\n"
        "Available sources will be listed in the profile information. "
        "Do NOT keep opportunities that are clearly irrelevant to the profile "
        "(e.g. junior roles for a senior candidate) or that violate the user's "
        "direction criteria."
    ),
)


@search_agent.tool
async def search_jobs(
    ctx: RunContext[SearchDeps],
    keywords: list[str],
    source_name: str,
    location: str | None = None,
) -> str:
    """Search a job source for opportunities matching the given keywords.

    Args:
        keywords: Search terms, e.g. ["cloud architect", "AWS"].
        source_name: Which source to search. Check profile info for available sources.
        location: Optional location filter, e.g. "Montreal, QC".
    """
    deps = ctx.deps
    _emit = deps.on_progress or (lambda _: None)

    # Check time budget
    elapsed = time.monotonic() - deps.start_time
    remaining = deps.time_limit - elapsed
    if remaining <= 0:
        _emit("Time limit reached — wrapping up.")
        return (
            "TIME IS UP. Stop searching and return your final results now. "
            f"You found {len(deps.found)} opportunities across "
            f"{len(deps.queries_tried)} queries."
        )

    source = deps.sources.get(source_name)
    if source is None:
        msg = f"Unknown source '{source_name}'. Available: {list(deps.sources.keys())}"
        _emit(msg)
        return msg

    query = SearchQuery(keywords=keywords, location=location, max_results=25)
    query_desc = f"{', '.join(keywords)} on {source_name}"
    deps.queries_tried.append(query_desc)

    mins_left = int(remaining // 60)
    secs_left = int(remaining % 60)
    loc_str = f" in {location}" if location else ""
    _emit(
        f"[{mins_left}m{secs_left:02d}s left] "
        f"Searching {source_name} for: [{', '.join(keywords)}]{loc_str}"
    )

    try:
        results = await source.scrape(query)
    except NotImplementedError:
        _emit(f"  {source_name} is not yet implemented — skipping.")
        return f"Source '{source_name}' is not yet implemented."
    except Exception as exc:
        logger.warning("Search failed for '%s': %s", query_desc, exc)
        _emit(f"  Search failed: {exc}")
        return f"Search failed: {exc}. Try different keywords or source."

    # Dedup and basic filter
    pre_filter: list[Opportunity] = []
    filtered_count = 0
    dupes = 0
    for opp in results:
        key = (opp.company.lower(), opp.title.lower(), opp.source.lower())
        if key in deps.seen_keys:
            dupes += 1
            continue
        if not _basic_filter(opp, deps.profile):
            filtered_count += 1
            continue
        deps.seen_keys.add(key)
        pre_filter.append(opp)

    # Location filter
    location_rejected = 0
    if pre_filter:
        new_opps = await filter_by_location(
            pre_filter, deps.profile, _model_override=deps._model_override
        )
        location_rejected = len(pre_filter) - len(new_opps)
        # Remove seen_keys for location-rejected opps so they can be rediscovered
        kept_keys = {
            (o.company.lower(), o.title.lower(), o.source.lower()) for o in new_opps
        }
        for opp in pre_filter:
            key = (opp.company.lower(), opp.title.lower(), opp.source.lower())
            if key not in kept_keys:
                deps.seen_keys.discard(key)
    else:
        new_opps = []

    # Persist and track
    for opp in new_opps:
        deps.found.append(opp)
        if deps.db_conn is not None:
            _persist_opportunity(deps.db_conn, opp)

    if not new_opps:
        detail = []
        if dupes:
            detail.append(f"{dupes} duplicates")
        if filtered_count:
            detail.append(
                f"{filtered_count} filtered (junior/low salary/excluded industry)"
            )
        if location_rejected:
            detail.append(f"{location_rejected} outside preferred locations")
        reason = ", ".join(detail) if detail else "no results from source"
        _emit(f"  0 new results ({reason}).")
        return f"Search '{query_desc}': 0 new results ({reason})."

    # Report findings
    for opp in new_opps[:5]:
        _emit(f"  + {opp.title} at {opp.company}")
    if len(new_opps) > 5:
        _emit(f"  ... and {len(new_opps) - 5} more")

    extra = []
    if dupes:
        extra.append(f"{dupes} dupes")
    if filtered_count:
        extra.append(f"{filtered_count} filtered out")
    if location_rejected:
        extra.append(f"{location_rejected} outside area")
    extra_str = f" ({', '.join(extra)})" if extra else ""
    _emit(f"  {len(new_opps)} new, {len(deps.found)} total unique{extra_str}")

    # Time status for the agent
    elapsed_now = time.monotonic() - deps.start_time
    remaining_now = deps.time_limit - elapsed_now
    time_note = ""
    if remaining_now < 60:
        time_note = " TIME ALMOST UP — wrap up after this."
    elif remaining_now < 120:
        time_note = f" ({int(remaining_now)}s remaining — consider wrapping up soon.)"

    titles = [f"- {o.title} at {o.company}" for o in new_opps[:10]]
    summary = (
        f"Search '{query_desc}': {len(new_opps)} new results "
        f"({len(deps.found)} total unique so far).{time_note}\n" + "\n".join(titles)
    )
    if len(new_opps) > 10:
        summary += f"\n... and {len(new_opps) - 10} more"

    return summary


@search_agent.tool
async def reject_opportunities(
    ctx: RunContext[SearchDeps],
    rejections: list[str],
    reason: str,
) -> str:
    """Remove opportunities that don't match the user's criteria.

    Args:
        rejections: List of company names to reject (case-insensitive partial match).
            Example: ["RBC", "TD Bank", "Desjardins"]
        reason: Why these are being rejected, e.g. "banking sector — user excluded it".
    """
    deps = ctx.deps
    _emit = deps.on_progress or (lambda _: None)

    if not rejections:
        return "No rejections specified."

    reject_lower = [r.lower() for r in rejections]
    before = len(deps.found)
    kept: list[Opportunity] = []
    removed: list[str] = []

    for opp in deps.found:
        company_lower = opp.company.lower()
        title_lower = opp.title.lower()
        if any(r in company_lower or r in title_lower for r in reject_lower):
            removed.append(f"{opp.company} — {opp.title}")
            deps.seen_keys.discard(
                (opp.company.lower(), opp.title.lower(), opp.source.lower())
            )
        else:
            kept.append(opp)

    deps.found = kept
    _emit(f"  Rejected {len(removed)} ({reason}): {len(deps.found)} remaining")

    if not removed:
        return f"No matches found for {rejections}. {len(deps.found)} opportunities remain."

    lines = [f"Rejected {len(removed)} opportunities ({reason}):"]
    for r in removed[:5]:
        lines.append(f"  - {r}")
    if len(removed) > 5:
        lines.append(f"  ... and {len(removed) - 5} more")
    lines.append(f"{len(deps.found)} opportunities remaining.")
    return "\n".join(lines)


def _persist_opportunity(conn: sqlite3.Connection, opp: Opportunity) -> None:
    """Save an opportunity to the database, skipping if already exists."""
    from emplaiyed.core.database import save_opportunity

    try:
        save_opportunity(conn, opp)
    except Exception as exc:
        logger.debug("Could not persist opportunity %s: %s", opp.title, exc)


def _basic_filter(opp: Opportunity, profile: Profile) -> bool:
    """Quick relevance check — rejects obvious mismatches."""
    title_lower = opp.title.lower()

    # Reject junior/intern roles
    junior_terms = [
        "intern",
        "co-op",
        "junior",
        "entry level",
        "entry-level",
        "stage",
        "stagiaire",
    ]
    if any(term in title_lower for term in junior_terms):
        return False

    # Reject if salary is clearly below minimum
    if (
        profile.aspirations
        and profile.aspirations.salary_minimum
        and opp.salary_max
        and opp.salary_max < profile.aspirations.salary_minimum * 0.8
    ):
        return False

    # Reject if company or description mentions an excluded industry
    if profile.aspirations and profile.aspirations.excluded_industries:
        haystack = f"{opp.company} {opp.title} {opp.description}".lower()
        for industry in profile.aspirations.excluded_industries:
            if industry.lower() in haystack:
                return False

    return True


def _build_search_prompt(profile: Profile, available_sources: list[str]) -> str:
    """Build the initial prompt from the user's profile."""
    parts = ["Find jobs for this candidate:\n"]
    parts.append(f"Name: {profile.name}")

    if profile.skills:
        parts.append(f"Skills: {', '.join(profile.skills[:15])}")

    if profile.aspirations:
        a = profile.aspirations
        if a.target_roles:
            parts.append(f"Target roles: {', '.join(a.target_roles)}")
        if a.geographic_preferences:
            parts.append(
                f"MANDATORY search locations (always pass one of these as the location "
                f"parameter): {', '.join(a.geographic_preferences)}"
            )
        if a.work_arrangement:
            parts.append(f"Work arrangement: {', '.join(a.work_arrangement)}")
        if a.salary_minimum or a.salary_target:
            parts.append(
                f"Salary: min ${a.salary_minimum or 0:,}, target ${a.salary_target or 0:,}"
            )
        if a.target_industries:
            parts.append(f"Target industries: {', '.join(a.target_industries)}")
        if a.excluded_industries:
            parts.append(
                f"EXCLUDED industries (reject these): {', '.join(a.excluded_industries)}"
            )

    if profile.address and profile.address.city:
        parts.append(
            f"Candidate lives in: {profile.address.city}, {profile.address.province_state or ''}"
        )

    if profile.employment_history:
        recent = profile.employment_history[0]
        parts.append(f"Most recent role: {recent.title} at {recent.company}")

    if profile.languages:
        langs = [f"{lang.language} ({lang.proficiency})" for lang in profile.languages]
        parts.append(f"Languages: {', '.join(langs)}")

    if profile.certifications:
        cert_names = [c.name for c in profile.certifications[:5]]
        parts.append(f"Certifications: {', '.join(cert_names)}")

    parts.append(f"\nAvailable sources to search: {', '.join(available_sources)}")

    return "\n".join(parts)


async def agentic_search(
    profile: Profile,
    sources: dict[str, BaseSource],
    *,
    direction: str | None = None,
    time_limit: int = DEFAULT_TIME_LIMIT,
    db_conn: sqlite3.Connection | None = None,
    on_progress: Callable[[str], None] | None = None,
    _model_override: Model | None = None,
) -> SearchResult:
    """Run the agentic search loop.

    Args:
        profile: User's profile with skills, aspirations, etc.
        sources: Available job sources keyed by name.
        direction: Optional free-text steering prompt.
        time_limit: Maximum search duration in seconds (default: 300 = 5 minutes).
        db_conn: Database connection for persisting opportunities as they're found.
        on_progress: Optional callback for real-time status updates.
        _model_override: For tests — pass TestModel() to avoid real API calls.

    Returns:
        SearchResult with all found opportunities and search summary.
    """
    _emit = on_progress or (lambda _: None)

    # Filter out sources that are stubs
    active_sources = {}
    for name, src in sources.items():
        if hasattr(src, "scrape"):
            active_sources[name] = src

    _emit(f"Active sources: {', '.join(active_sources.keys())}")
    _emit(f"Time limit: {time_limit // 60}m{time_limit % 60:02d}s")

    # Seed seen_keys from existing active opportunities so we don't
    # re-find jobs that already have an active application. Passed/rejected
    # opportunities are excluded so they can be re-discovered.
    initial_seen: set[tuple[str, str, str]] = set()
    if db_conn is not None:
        from emplaiyed.core.database import active_opportunity_keys

        initial_seen = active_opportunity_keys(db_conn)
        _emit(f"Skipping {len(initial_seen)} already-active opportunities")

    deps = SearchDeps(
        profile=profile,
        sources=active_sources,
        time_limit=time_limit,
        db_conn=db_conn,
        on_progress=on_progress,
        seen_keys=initial_seen,
        _model_override=_model_override,
    )

    prompt = _build_search_prompt(profile, list(active_sources.keys()))

    if direction:
        _emit(f"Direction: {direction}")
        prompt = (
            f"USER DIRECTION (this overrides default strategy): {direction}\n\n"
            f"Prioritize searches that match this direction. Still use the "
            f"candidate's profile for filtering, but let the direction guide "
            f"your query strategy.\n\n{prompt}"
        )

    if _model_override is not None:
        model = _model_override
    else:
        from emplaiyed.llm.engine import _build_model

        model = _build_model(SEARCH_MODEL)

    # High request limit as safety net — time is the real constraint.
    try:
        result = await search_agent.run(
            prompt,
            deps=deps,
            usage_limits=UsageLimits(request_limit=50),
            model=model,
        )
        output = result.output
    except UsageLimitExceeded:
        _emit("Request limit reached — returning what we found.")
        output = SearchResult(summary="Stopped: request limit reached.")

    # Ground truth is in deps, not the agent's structured output
    output.opportunities = deps.found
    output.queries_used = deps.queries_tried

    elapsed = time.monotonic() - deps.start_time
    _emit(
        f"Done — {len(output.opportunities)} opportunities found "
        f"across {len(output.queries_used)} queries "
        f"in {int(elapsed)}s."
    )

    return output
