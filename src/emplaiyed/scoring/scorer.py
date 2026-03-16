"""Opportunity scoring — ranks opportunities against a user profile.

Uses a single LLM call to score ALL opportunities at once so scores are
relative to each other, not absolute. A job is good or bad compared to
the other options available, not in isolation.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.database import save_application
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Opportunity,
    Profile,
    ScoredOpportunity,
)
from emplaiyed.core.prompt_helpers import format_skills
from emplaiyed.llm.engine import complete_structured

logger = logging.getLogger(__name__)

# Max opportunities per batch — keeps prompt under context limits.
_BATCH_SIZE = 50


class _ScoredItem(BaseModel):
    """LLM output for one opportunity within a batch."""

    index: int = Field(description="0-based index matching the opportunity list")
    score: int = Field(ge=0, le=100)
    justification: str = Field(max_length=120)
    day_to_day: str
    why_it_fits: str


class _BatchScoreResult(BaseModel):
    """LLM output for a batch of scored opportunities."""

    scores: list[_ScoredItem]


_BATCH_PROMPT = """\
You are a job-matching expert. Score ALL the following opportunities for this \
candidate on a scale of 0-100.

IMPORTANT: Scores are RELATIVE. Compare opportunities against each other. \
The best match in the batch should score highest. Spread scores out — \
don't cluster everything at 70-80. Use the full 0-100 range.

HARD EXCLUSION RULE:
If the opportunity is in an excluded industry, score it **0** regardless of \
all other criteria. Use your judgement — "National Bank of Canada" is banking, \
"Desjardins" is banking/insurance, etc. The company name and description are \
enough to determine the industry.

Excluded industries: {excluded_industries}

Scoring criteria (weight each roughly equally):
1. **Skills match** — Do the candidate's skills align with the job requirements?
2. **Seniority fit** — Does the role match the candidate's experience level?
3. **Location** — Is the job in or near the candidate's preferred locations?
4. **Salary** — Is the salary within the candidate's expected range?
5. **Role alignment** — Does the title/description match target roles?

A score of 80+ means strong fit. 50-79 means partial fit. Below 50 means poor fit.

For each opportunity provide:
- index: the 0-based index from the list below
- score: 0-100
- justification: a single short sentence under 100 characters. No commas, no clauses.
- day_to_day: 2-3 sentence description of what the candidate would do day-to-day. \
Always end with a sentence listing the likely tech stack (languages, frameworks, \
tools, cloud services) they would work with — infer from the job description, \
company context, and industry norms even when not explicitly stated.
- why_it_fits: 2-3 sentence explanation of why this role fits the candidate

CANDIDATE PROFILE:
- Name: {name}
- Skills: {skills}
- Target roles: {target_roles}
- Location preference: {location_prefs}
- Salary range: {salary_range}
- Experience: {experience}

OPPORTUNITIES TO SCORE:
{opportunities_block}
"""


def _format_profile_block(profile: Profile) -> dict[str, str]:
    """Extract profile fields for prompt formatting."""
    skills = format_skills(profile, limit=15)

    target_roles = "Not specified"
    location_prefs = "Not specified"
    salary_range = "Not specified"
    if profile.aspirations:
        if profile.aspirations.target_roles:
            target_roles = ", ".join(profile.aspirations.target_roles)
        if profile.aspirations.geographic_preferences:
            location_prefs = ", ".join(profile.aspirations.geographic_preferences)
        if profile.aspirations.salary_minimum or profile.aspirations.salary_target:
            parts = []
            if profile.aspirations.salary_minimum:
                parts.append(f"min ${profile.aspirations.salary_minimum:,}")
            if profile.aspirations.salary_target:
                parts.append(f"target ${profile.aspirations.salary_target:,}")
            salary_range = ", ".join(parts)

    experience = "Not specified"
    if profile.employment_history:
        exp_parts = [
            f"{e.title} at {e.company}" for e in profile.employment_history[:3]
        ]
        experience = "; ".join(exp_parts)

    excluded_industries = "None"
    if profile.aspirations and profile.aspirations.excluded_industries:
        excluded_industries = ", ".join(profile.aspirations.excluded_industries)

    return {
        "name": profile.name,
        "skills": skills,
        "target_roles": target_roles,
        "location_prefs": location_prefs,
        "salary_range": salary_range,
        "experience": experience,
        "excluded_industries": excluded_industries,
    }


def _format_opp_block(index: int, opp: Opportunity) -> str:
    """Format a single opportunity for the batch prompt."""
    salary = "Not specified"
    if opp.salary_min or opp.salary_max:
        parts = []
        if opp.salary_min:
            parts.append(f"${opp.salary_min:,}")
        if opp.salary_max and opp.salary_max != opp.salary_min:
            parts.append(f"${opp.salary_max:,}")
        salary = " - ".join(parts)

    desc = opp.description[:500] if opp.description else "No description"
    return (
        f"[{index}] {opp.title} at {opp.company}\n"
        f"    Location: {opp.location or 'Not specified'} | Salary: {salary}\n"
        f"    Description: {desc}\n"
    )


def _build_batch_prompt(profile: Profile, opportunities: list[Opportunity]) -> str:
    """Build a single prompt that scores all opportunities at once."""
    profile_fields = _format_profile_block(profile)
    opp_blocks = "\n".join(
        _format_opp_block(i, opp) for i, opp in enumerate(opportunities)
    )
    return _BATCH_PROMPT.format(**profile_fields, opportunities_block=opp_blocks)


async def score_opportunity(
    profile: Profile,
    opportunity: Opportunity,
    *,
    _model_override: Model | None = None,
) -> ScoredOpportunity:
    """Score a single opportunity against a profile.

    For relative scoring, prefer ``score_opportunities`` which scores
    all opportunities in a single batch.
    """
    results = await score_opportunities(
        profile, [opportunity], _model_override=_model_override
    )
    return results[0]


async def _score_batch(
    profile: Profile,
    batch: list[Opportunity],
    *,
    _model_override: Model | None = None,
) -> list[ScoredOpportunity]:
    """Score a batch of opportunities in a single LLM call."""
    from emplaiyed.llm.config import SCORING_MODEL

    prompt = _build_batch_prompt(profile, batch)
    logger.debug(
        "Batch scoring %d opportunities (prompt_len=%d)", len(batch), len(prompt)
    )

    try:
        result = await complete_structured(
            prompt,
            output_type=_BatchScoreResult,
            model=SCORING_MODEL,
            _model_override=_model_override,
        )
    except Exception as exc:
        logger.warning("Batch scoring failed: %s", exc)
        return [
            ScoredOpportunity(
                opportunity=opp,
                score=0,
                justification=f"Scoring failed: {exc}",
            )
            for opp in batch
        ]

    # Map LLM results back to opportunities by index
    score_map: dict[int, _ScoredItem] = {s.index: s for s in result.scores}
    scored: list[ScoredOpportunity] = []
    for i, opp in enumerate(batch):
        if i in score_map:
            s = score_map[i]
            scored.append(
                ScoredOpportunity(
                    opportunity=opp,
                    score=s.score,
                    justification=s.justification,
                    day_to_day=s.day_to_day,
                    why_it_fits=s.why_it_fits,
                )
            )
        else:
            logger.warning(
                "LLM skipped opportunity %d (%s at %s)", i, opp.title, opp.company
            )
            scored.append(
                ScoredOpportunity(
                    opportunity=opp,
                    score=0,
                    justification="Not scored by LLM",
                )
            )

    return scored


async def score_opportunities(
    profile: Profile,
    opportunities: list[Opportunity],
    *,
    db_conn: sqlite3.Connection | None = None,
    _model_override: Model | None = None,
) -> list[ScoredOpportunity]:
    """Score all opportunities in batches, then sort by score.

    Opportunities are scored in batches of up to 50 in a single LLM call
    so scores are relative to each other. When *db_conn* is provided,
    creates an Application for each opportunity in SCORED status.
    """
    if not opportunities:
        return []

    # Split into batches and score each
    all_scored: list[ScoredOpportunity] = []
    for i in range(0, len(opportunities), _BATCH_SIZE):
        batch = opportunities[i : i + _BATCH_SIZE]
        batch_results = await _score_batch(
            profile, batch, _model_override=_model_override
        )
        all_scored.extend(batch_results)

    all_scored.sort(key=lambda s: s.score, reverse=True)
    logger.debug(
        "Scored %d opportunities in %d batch(es)",
        len(all_scored),
        (len(opportunities) + _BATCH_SIZE - 1) // _BATCH_SIZE,
    )

    if db_conn is not None:
        from emplaiyed.llm.config import SCORE_THRESHOLD

        now = datetime.now()
        below_count = 0
        for so in all_scored:
            if so.score < SCORE_THRESHOLD:
                status = ApplicationStatus.BELOW_THRESHOLD
                below_count += 1
            else:
                status = ApplicationStatus.SCORED
            app = Application(
                opportunity_id=so.opportunity.id,
                status=status,
                score=so.score,
                justification=so.justification,
                day_to_day=so.day_to_day,
                why_it_fits=so.why_it_fits,
                created_at=now,
                updated_at=now,
            )
            save_application(db_conn, app)
        above_count = len(all_scored) - below_count
        logger.debug(
            "Created %d applications (%d SCORED, %d BELOW_THRESHOLD, threshold=%d)",
            len(all_scored),
            above_count,
            below_count,
            SCORE_THRESHOLD,
        )

    return all_scored
