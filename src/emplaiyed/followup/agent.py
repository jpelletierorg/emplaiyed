"""Follow-up agent — identifies stale applications and generates follow-ups."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from pydantic import BaseModel
from pydantic_ai.models import Model

from emplaiyed.core.database import (
    get_opportunity,
    list_applications,
    list_interactions,
    save_interaction,
)
from emplaiyed.core.models import (
    ApplicationStatus,
    Interaction,
    InteractionType,
    Opportunity,
    Profile,
)
from emplaiyed.llm.engine import complete_structured
from emplaiyed.tracker.state_machine import can_transition, transition

logger = logging.getLogger(__name__)


class FollowUpDraft(BaseModel):
    """LLM output for a follow-up message."""

    subject: str
    body: str


_FOLLOWUP_PROMPT = """\
Write a brief, professional follow-up email for a job application.
This is follow-up #{followup_number}.

Rules:
- Keep it under 100 words
- Reference the original application
- Be polite but show continued interest
- Don't be pushy or desperate

CANDIDATE: {name}
COMPANY: {company}
ROLE: {title}
DAYS SINCE LAST CONTACT: {days_since}
"""


def find_stale_applications(
    db_conn: sqlite3.Connection,
    stale_days: int = 5,
) -> list[tuple[str, str, Opportunity, int]]:
    """Find applications with no response for stale_days+.

    Returns list of (application_id, next_status, opportunity, days_since).
    """
    stale: list[tuple[str, str, Opportunity, int]] = []
    cutoff = datetime.now() - timedelta(days=stale_days)

    for status in (
        ApplicationStatus.OUTREACH_SENT,
        ApplicationStatus.FOLLOW_UP_1,
    ):
        apps = list_applications(db_conn, status=status)
        for app in apps:
            if app.updated_at <= cutoff:
                opp = get_opportunity(db_conn, app.opportunity_id)
                if opp is None:
                    continue

                days = (datetime.now() - app.updated_at).days
                if status == ApplicationStatus.OUTREACH_SENT:
                    next_status = "FOLLOW_UP_1"
                else:
                    next_status = "FOLLOW_UP_2"

                stale.append((app.id, next_status, opp, days))

    logger.debug("Found %d stale applications", len(stale))
    return stale


async def draft_followup(
    profile: Profile,
    opportunity: Opportunity,
    followup_number: int,
    days_since: int,
    *,
    _model_override: Model | None = None,
) -> FollowUpDraft:
    """Generate a follow-up email draft."""
    prompt = _FOLLOWUP_PROMPT.format(
        name=profile.name,
        company=opportunity.company,
        title=opportunity.title,
        followup_number=followup_number,
        days_since=days_since,
    )
    return await complete_structured(
        prompt, output_type=FollowUpDraft, _model_override=_model_override
    )


def send_followup(
    db_conn: sqlite3.Connection,
    application_id: str,
    draft: FollowUpDraft,
    target_status: ApplicationStatus,
) -> None:
    """Record the follow-up and transition the application."""
    interaction = Interaction(
        application_id=application_id,
        type=InteractionType.FOLLOW_UP,
        direction="outbound",
        channel="email",
        content=f"Subject: {draft.subject}\n\n{draft.body}",
        created_at=datetime.now(),
    )
    save_interaction(db_conn, interaction)
    transition(db_conn, application_id, target_status)
    logger.debug("Follow-up sent for %s → %s", application_id, target_status.value)
