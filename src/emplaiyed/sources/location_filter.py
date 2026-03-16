"""LLM-based location filter for job opportunities.

Uses a cheap/fast LLM call to determine whether each opportunity's location
is compatible with the candidate's geographic preferences. Fully remote jobs
always pass. Jobs with no location field pass (benefit of the doubt).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.models import Opportunity, Profile
from emplaiyed.llm.config import LOCATION_FILTER_MODEL

logger = logging.getLogger(__name__)

_BATCH_SIZE = 20


class LocationVerdict(BaseModel):
    """LLM verdict for a single opportunity's location compatibility."""

    index: int
    compatible: bool
    reason: str = Field(description="Brief explanation, under 80 chars")


class LocationFilterResult(BaseModel):
    """Batch result from the location filter LLM call."""

    verdicts: list[LocationVerdict]


_SYSTEM_PROMPT = """\
You are a location compatibility checker. Your ONLY job is to determine whether
a job opportunity's location is compatible with a candidate's geographic
preferences.

Rules:
1. If the job is explicitly "Remote", "Work from home", "Télétravail",
   or "100% remote" with NO specific city requirement, it is COMPATIBLE.
2. If the job location is in or near one of the candidate's preferred
   locations (same city, same metropolitan area, nearby suburb), it is COMPATIBLE.
3. If the job location is ambiguous or not specified, it is COMPATIBLE
   (benefit of the doubt).
4. If the job is "Hybrid" or "On-site" in a city that is NOT in or near
   the candidate's preferred locations, it is NOT COMPATIBLE.
5. Use your knowledge of Canadian geography. For example:
   - Longueuil, Brossard, Saint-Hubert, Boucherville, Saint-Lambert are on
     the "South Shore of Montreal"
   - Laval, Terrebonne, Blainville are in the "Greater Montreal Area"
   - Quebec City, Ottawa, Toronto, Vancouver, Calgary are NOT in the
     Greater Montreal Area
6. If the job says "Remote" but specifies a city far from the candidate
   (e.g., "Remote - Vancouver"), it IS compatible because the candidate can
   work remotely.
7. If the job says "Hybrid - Vancouver" it is NOT compatible because hybrid
   requires physical presence in Vancouver.

Return your verdict for EVERY opportunity listed. Do not skip any."""


def _is_remote_only(location: str) -> bool:
    """Return True if the location looks like a fully-remote role (no hybrid)."""
    loc_lower = location.lower()
    if "hybrid" in loc_lower:
        return False
    remote_keywords = ["remote", "télétravail", "teletravail", "work from home"]
    return any(kw in loc_lower for kw in remote_keywords)


async def filter_by_location(
    opportunities: list[Opportunity],
    profile: Profile,
    *,
    _model_override: Model | None = None,
) -> list[Opportunity]:
    """Filter opportunities by location compatibility using an LLM.

    Quick-pass rules (no LLM call needed):
    - No geographic preferences in profile -> return all.
    - Opportunity has no location -> pass (benefit of the doubt).
    - Opportunity location contains "remote" without "hybrid" -> pass.

    Everything else is batched and sent to a cheap LLM for evaluation.
    If the LLM call fails, we fail-open and keep all opportunities.
    """
    # No preferences -> nothing to filter
    if not profile.aspirations or not profile.aspirations.geographic_preferences:
        return list(opportunities)

    # Build location preference string for the prompt
    prefs = list(profile.aspirations.geographic_preferences)
    city = ""
    province = ""
    if profile.address and profile.address.city:
        city = profile.address.city
        province = profile.address.province_state or ""
        candidate_location = f"{city}, {province}".strip(", ")
    else:
        candidate_location = "Not specified"

    # Partition into quick-pass and needs-evaluation
    kept: list[Opportunity] = []
    to_evaluate: list[Opportunity] = []

    for opp in opportunities:
        if not opp.location or not opp.location.strip():
            kept.append(opp)
        elif _is_remote_only(opp.location):
            kept.append(opp)
        else:
            to_evaluate.append(opp)

    if not to_evaluate:
        return kept

    # Process in batches
    for batch_start in range(0, len(to_evaluate), _BATCH_SIZE):
        batch = to_evaluate[batch_start : batch_start + _BATCH_SIZE]
        try:
            approved = await _evaluate_batch(
                batch, prefs, candidate_location, _model_override
            )
            kept.extend(approved)
        except Exception:
            # Fail-open: if the LLM call fails, keep all opportunities in this batch
            logger.warning(
                "Location filter LLM call failed for batch starting at %d — "
                "keeping all %d opportunities (fail-open).",
                batch_start,
                len(batch),
                exc_info=True,
            )
            kept.extend(batch)

    return kept


async def _evaluate_batch(
    batch: list[Opportunity],
    prefs: list[str],
    candidate_location: str,
    _model_override: Model | None,
) -> list[Opportunity]:
    """Evaluate a batch of opportunities via a single LLM call."""
    from emplaiyed.llm.engine import complete_structured

    # Build the user prompt
    opp_lines = []
    for i, opp in enumerate(batch):
        opp_lines.append(
            f"[{i}] {opp.title} at {opp.company} — Location: {opp.location}"
        )

    prompt = (
        f"Candidate's geographic preferences: {', '.join(prefs)}\n"
        f"Candidate lives in: {candidate_location}\n\n"
        f"Opportunities to evaluate:\n"
        + "\n".join(opp_lines)
        + "\n\nFor each opportunity, determine if its location is compatible."
    )

    result = await complete_structured(
        prompt,
        LocationFilterResult,
        system_prompt=_SYSTEM_PROMPT,
        model=LOCATION_FILTER_MODEL,
        _model_override=_model_override,
    )

    # Build a set of compatible indices
    compatible_indices: set[int] = set()
    for verdict in result.verdicts:
        if verdict.compatible:
            compatible_indices.add(verdict.index)
        else:
            opp = batch[verdict.index] if verdict.index < len(batch) else None
            if opp:
                logger.debug(
                    "Location filter rejected: %s at %s (%s) — %s",
                    opp.title,
                    opp.company,
                    opp.location,
                    verdict.reason,
                )

    return [opp for i, opp in enumerate(batch) if i in compatible_indices]
