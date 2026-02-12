"""Outreach email drafter — generates tailored application emails.

Uses the LLM to produce a personalized email for each opportunity,
drawing on the user's profile and the job description.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from pydantic import BaseModel
from pydantic_ai.models import Model

from emplaiyed.core.database import (
    get_application,
    list_applications,
    get_opportunity,
    save_interaction,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Interaction,
    InteractionType,
    Opportunity,
    Profile,
)
from emplaiyed.llm.engine import complete_structured
from emplaiyed.tracker.state_machine import transition

logger = logging.getLogger(__name__)


class OutreachDraft(BaseModel):
    """LLM output for an outreach email."""

    subject: str
    body: str


_OUTREACH_PROMPT = """\
You are a professional job application writer. Write a concise, compelling
application email for the following opportunity.

Rules:
- Be professional but human — no generic filler
- Lead with the candidate's most relevant experience for THIS specific role
- Keep it under 200 words
- Don't be sycophantic or desperate
- Include a clear subject line

CANDIDATE:
- Name: {name}
- Key skills: {skills}
- Recent role: {recent_role}
- Target: {target_roles}

OPPORTUNITY:
- Company: {company}
- Title: {title}
- Location: {location}
- Description (first 1000 chars):
{description}
"""


async def draft_outreach(
    profile: Profile,
    opportunity: Opportunity,
    *,
    _model_override: Model | None = None,
) -> OutreachDraft:
    """Generate an outreach email draft for an opportunity."""
    recent_role = "Not specified"
    if profile.employment_history:
        e = profile.employment_history[0]
        recent_role = f"{e.title} at {e.company}"

    target_roles = "Not specified"
    if profile.aspirations and profile.aspirations.target_roles:
        target_roles = ", ".join(profile.aspirations.target_roles)

    prompt = _OUTREACH_PROMPT.format(
        name=profile.name,
        skills=", ".join(profile.skills[:10]) if profile.skills else "Not specified",
        recent_role=recent_role,
        target_roles=target_roles,
        company=opportunity.company,
        title=opportunity.title,
        location=opportunity.location or "Not specified",
        description=(opportunity.description[:1000] if opportunity.description else "No description"),
    )

    logger.debug("Drafting outreach for %s at %s", opportunity.title, opportunity.company)
    return await complete_structured(
        prompt, output_type=OutreachDraft, _model_override=_model_override
    )


def send_outreach(
    db_conn: sqlite3.Connection,
    application_id: str,
    draft: OutreachDraft,
) -> None:
    """Record the outreach as an interaction and transition to OUTREACH_SENT.

    In a real implementation this would send the email via SMTP.
    For now it records the intent and transitions the state.
    """
    interaction = Interaction(
        application_id=application_id,
        type=InteractionType.EMAIL_SENT,
        direction="outbound",
        channel="email",
        content=f"Subject: {draft.subject}\n\n{draft.body}",
        created_at=datetime.now(),
    )
    save_interaction(db_conn, interaction)
    transition(db_conn, application_id, ApplicationStatus.OUTREACH_SENT)
    logger.debug("Outreach sent for application %s", application_id)
