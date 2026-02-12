"""Opportunity scoring — ranks opportunities against a user profile.

Uses the LLM to evaluate how well each opportunity matches the user's
skills, experience, aspirations, and location preferences. Returns a
0-100 score with a short justification.
"""

from __future__ import annotations

import asyncio
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


class _ScoreResult(BaseModel):
    """LLM output for a single scoring call."""

    score: int = Field(ge=0, le=100)
    justification: str = Field(max_length=120)
    day_to_day: str
    why_it_fits: str


_SCORE_PROMPT = """\
You are a job-matching expert. Score how well this opportunity matches the
candidate's profile on a scale of 0-100.

Scoring criteria (weight each roughly equally):
1. **Skills match** — Do the candidate's skills align with the job requirements?
2. **Seniority fit** — Does the role match the candidate's experience level?
3. **Location** — Is the job in or near the candidate's preferred locations?
4. **Salary** — Is the salary within the candidate's expected range?
5. **Role alignment** — Does the title/description match target roles?

A score of 80+ means strong fit. 50-79 means partial fit. Below 50 means poor fit.

Your justification MUST be a single short sentence under 100 characters. No commas, no clauses.

Also provide:
- day_to_day: 2-3 sentence description of what the candidate would do day-to-day in this role, based on the job description
- why_it_fits: 2-3 sentence explanation of why this role fits the candidate's profile and aspirations

CANDIDATE PROFILE:
- Name: {name}
- Skills: {skills}
- Target roles: {target_roles}
- Location preference: {location_prefs}
- Salary range: {salary_range}
- Experience: {experience}

OPPORTUNITY:
- Title: {opp_title}
- Company: {opp_company}
- Location: {opp_location}
- Salary: {opp_salary}
- Description (first 1500 chars):
{opp_description}
"""


def _build_score_prompt(profile: Profile, opportunity: Opportunity) -> str:
    """Build the scoring prompt from profile + opportunity data."""
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

    opp_salary = "Not specified"
    if opportunity.salary_min or opportunity.salary_max:
        parts = []
        if opportunity.salary_min:
            parts.append(f"${opportunity.salary_min:,}")
        if opportunity.salary_max and opportunity.salary_max != opportunity.salary_min:
            parts.append(f"${opportunity.salary_max:,}")
        opp_salary = " - ".join(parts)

    return _SCORE_PROMPT.format(
        name=profile.name,
        skills=skills,
        target_roles=target_roles,
        location_prefs=location_prefs,
        salary_range=salary_range,
        experience=experience,
        opp_title=opportunity.title,
        opp_company=opportunity.company,
        opp_location=opportunity.location or "Not specified",
        opp_salary=opp_salary,
        opp_description=(opportunity.description[:1500] if opportunity.description else "No description"),
    )


async def score_opportunity(
    profile: Profile,
    opportunity: Opportunity,
    *,
    _model_override: Model | None = None,
) -> ScoredOpportunity:
    """Score a single opportunity against a profile."""
    prompt = _build_score_prompt(profile, opportunity)
    logger.debug(
        "Scoring %s at %s (prompt_len=%d)",
        opportunity.title,
        opportunity.company,
        len(prompt),
    )

    result = await complete_structured(
        prompt,
        output_type=_ScoreResult,
        _model_override=_model_override,
    )

    return ScoredOpportunity(
        opportunity=opportunity,
        score=result.score,
        justification=result.justification,
        day_to_day=result.day_to_day,
        why_it_fits=result.why_it_fits,
    )


async def score_opportunities(
    profile: Profile,
    opportunities: list[Opportunity],
    *,
    db_conn: sqlite3.Connection | None = None,
    _model_override: Model | None = None,
) -> list[ScoredOpportunity]:
    """Score a list of opportunities and optionally create Application records.

    When *db_conn* is provided, creates an Application for each opportunity
    in SCORED status.

    Returns scored opportunities sorted by score (highest first).
    """
    async def _safe_score(opp: Opportunity) -> ScoredOpportunity:
        try:
            return await score_opportunity(
                profile, opp, _model_override=_model_override
            )
        except Exception as exc:
            logger.warning("Failed to score %s at %s: %s", opp.title, opp.company, exc)
            return ScoredOpportunity(
                opportunity=opp,
                score=0,
                justification=f"Scoring failed: {exc}",
            )

    scored = list(await asyncio.gather(*(_safe_score(opp) for opp in opportunities)))
    scored.sort(key=lambda s: s.score, reverse=True)
    logger.debug("Scored %d opportunities", len(scored))

    if db_conn is not None:
        now = datetime.now()
        for so in scored:
            app = Application(
                opportunity_id=so.opportunity.id,
                status=ApplicationStatus.SCORED,
                score=so.score,
                justification=so.justification,
                day_to_day=so.day_to_day,
                why_it_fits=so.why_it_fits,
                created_at=now,
                updated_at=now,
            )
            save_application(db_conn, app)
        logger.debug("Created %d SCORED applications", len(scored))

    return scored
