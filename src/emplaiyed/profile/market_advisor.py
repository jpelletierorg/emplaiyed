"""Market Gap Advisor — compares profile against market demand.

Analyzes scored opportunities in the database to identify skills,
experience patterns, and qualifications the candidate should develop
to improve their competitiveness for target roles.
"""

from __future__ import annotations

import logging
import sqlite3

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.database import list_applications_by_statuses
from emplaiyed.core.models import ApplicationStatus, Opportunity, Profile
from emplaiyed.llm.engine import complete_structured

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class SkillGap(BaseModel):
    """A skill that the market demands but the candidate lacks or under-highlights."""

    skill: str
    demand_signal: str = Field(
        description="How often/strongly this appears in target jobs"
    )
    recommendation: str = Field(description="What the candidate should do about it")
    priority: str = Field(description="high, medium, or low")


class ExperienceGap(BaseModel):
    """An experience pattern the candidate should highlight or develop."""

    area: str
    market_expectation: str
    candidate_status: str = Field(description="What the candidate currently has")
    recommendation: str


class ProjectSuggestion(BaseModel):
    """A project the candidate could build to strengthen their profile."""

    name: str
    description: str
    skills_demonstrated: list[str]
    estimated_effort: str = Field(description="e.g. '1 weekend', '2-4 weeks'")


class CertificationSuggestion(BaseModel):
    """A certification worth pursuing."""

    name: str
    issuer: str
    relevance: str


class ProfileWording(BaseModel):
    """A suggestion to improve how existing experience is presented."""

    current: str
    suggested: str
    reason: str


class MarketGapReport(BaseModel):
    """Full market gap analysis report."""

    summary: str = Field(description="2-3 sentence overall assessment")
    skill_gaps: list[SkillGap] = Field(default_factory=list)
    experience_gaps: list[ExperienceGap] = Field(default_factory=list)
    project_suggestions: list[ProjectSuggestion] = Field(default_factory=list)
    certification_suggestions: list[CertificationSuggestion] = Field(
        default_factory=list
    )
    profile_wording: list[ProfileWording] = Field(default_factory=list)
    strengths: list[str] = Field(
        default_factory=list,
        description="Things the candidate already does well relative to market demand",
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_ADVISOR_SYSTEM_PROMPT = """\
You are a career strategist specializing in software engineering and applied AI \
roles. You analyze job market signals to give candidates honest, actionable \
advice about gaps between their profile and what employers are actually hiring for.

Be specific and honest. Do NOT pad the report with generic advice like \
"keep learning" or "stay current." Every recommendation must be tied to a \
concrete signal from the job descriptions provided.

If the candidate is already well-positioned, say so. Don't invent gaps.
"""


def _build_advisor_prompt(
    profile: Profile,
    opportunities: list[Opportunity],
) -> str:
    """Build the prompt for market gap analysis."""
    parts = [
        "Analyze the gap between this candidate's profile and what the market demands.",
        "",
        "## Candidate Profile",
        f"Name: {profile.name}",
    ]

    if profile.skills:
        parts.append(f"Skills: {', '.join(profile.skills)}")

    if profile.employment_history:
        parts.append("\nEmployment:")
        for emp in profile.employment_history:
            start = emp.start_date.isoformat() if emp.start_date else "?"
            end = emp.end_date.isoformat() if emp.end_date else "Present"
            parts.append(f"  {emp.title} at {emp.company} ({start} – {end})")
            for h in emp.highlights:
                parts.append(f"    - {h}")

    if profile.education:
        parts.append("\nEducation:")
        for edu in profile.education:
            parts.append(f"  {edu.degree} in {edu.field}, {edu.institution}")

    if profile.certifications:
        parts.append("\nCertifications:")
        for cert in profile.certifications:
            expiry = ""
            if cert.expiry_date:
                expiry = f" (expired {cert.expiry_date.isoformat()})"
            parts.append(f"  {cert.name} ({cert.issuer}){expiry}")

    if profile.aspirations:
        asp = profile.aspirations
        if asp.target_roles:
            parts.append(f"\nTarget roles: {', '.join(asp.target_roles)}")
        if asp.salary_target:
            parts.append(f"Salary target: ${asp.salary_target:,}")

    parts.append(f"\n## Market Signal: {len(opportunities)} Relevant Job Postings\n")
    for i, opp in enumerate(opportunities[:30]):  # Cap at 30 to stay in context
        desc = opp.description[:400] if opp.description else "No description"
        parts.append(f"[{i + 1}] {opp.title} at {opp.company}")
        parts.append(f"    {desc}")
        parts.append("")

    parts.extend(
        [
            "## Instructions",
            "Compare the candidate's profile against the aggregate patterns in these job postings.",
            "Identify:",
            "1. Skills that appear frequently in the jobs but are missing or weak in the profile",
            "2. Experience patterns the market expects that the candidate should develop or highlight",
            "3. Concrete project ideas the candidate could build to fill gaps",
            "4. Certifications worth pursuing (if any)",
            "5. Ways to reword existing experience to better match market language",
            "6. Strengths the candidate already has relative to market demand",
            "",
            "Be brutally honest. The candidate wants to know where they fall short, "
            "not be reassured.",
        ]
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


async def analyze_market_gaps(
    profile: Profile,
    db_conn: sqlite3.Connection,
    *,
    _model_override: Model | None = None,
) -> MarketGapReport:
    """Analyze profile against scored opportunities in the database.

    Pulls opportunities from the database (SCORED and above statuses),
    sends them with the profile to an LLM, and returns a structured
    MarketGapReport with actionable recommendations.
    """
    from emplaiyed.core.database import get_opportunity
    from emplaiyed.llm.config import DEFAULT_MODEL

    # Get all scored+ applications
    statuses = [
        ApplicationStatus.SCORED,
        ApplicationStatus.OUTREACH_PENDING,
        ApplicationStatus.OUTREACH_SENT,
        ApplicationStatus.FOLLOW_UP_PENDING,
        ApplicationStatus.FOLLOW_UP_1,
        ApplicationStatus.FOLLOW_UP_2,
        ApplicationStatus.RESPONSE_RECEIVED,
        ApplicationStatus.INTERVIEW_SCHEDULED,
        ApplicationStatus.INTERVIEW_COMPLETED,
        ApplicationStatus.OFFER_RECEIVED,
    ]
    apps = list_applications_by_statuses(db_conn, statuses)

    if not apps:
        return MarketGapReport(
            summary="No scored opportunities found in the database. "
            "Run a search first with `emplaiyed sources search` to populate market data.",
        )

    # Sort by score descending, take top 50
    apps.sort(key=lambda a: a.score or 0, reverse=True)
    top_apps = apps[:50]

    # Load opportunity details
    opportunities: list[Opportunity] = []
    for app in top_apps:
        opp = get_opportunity(db_conn, app.opportunity_id)
        if opp:
            opportunities.append(opp)

    if not opportunities:
        return MarketGapReport(
            summary="Could not load opportunity details from the database.",
        )

    prompt = _build_advisor_prompt(profile, opportunities)

    return await complete_structured(
        prompt,
        MarketGapReport,
        system_prompt=_ADVISOR_SYSTEM_PROMPT,
        model=DEFAULT_MODEL,
        _model_override=_model_override,
    )
