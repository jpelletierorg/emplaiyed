"""Email classifier — uses LLM structured output to categorise incoming emails.

Classifies emails into job-search-relevant categories and flags
those requiring action so the monitor can create work items.
"""

from __future__ import annotations

import enum
import logging

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.llm.config import INBOX_MODEL
from emplaiyed.llm.engine import complete_structured

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification schema
# ---------------------------------------------------------------------------


class EmailCategory(str, enum.Enum):
    INTERVIEW_INVITE = "INTERVIEW_INVITE"
    OFFER = "OFFER"
    REJECTION = "REJECTION"
    FOLLOW_UP_REPLY = "FOLLOW_UP_REPLY"
    RECRUITER_OUTREACH = "RECRUITER_OUTREACH"
    APPLICATION_CONFIRMATION = "APPLICATION_CONFIRMATION"
    IRRELEVANT = "IRRELEVANT"


class EmailClassification(BaseModel):
    """Structured output from the LLM email classifier."""

    category: EmailCategory
    requires_action: bool = Field(
        description="True if the user needs to do something (reply, prepare, etc.)"
    )
    urgency: str = Field(description='One of "high", "medium", or "low"')
    summary: str = Field(
        description="One-line summary suitable for a Telegram notification"
    )
    suggested_next_step: str | None = Field(
        default=None,
        description="Optional concrete next step for the user",
    )


# Categories that warrant creating a work item
ACTIONABLE_CATEGORIES: frozenset[EmailCategory] = frozenset(
    {
        EmailCategory.INTERVIEW_INVITE,
        EmailCategory.OFFER,
        EmailCategory.FOLLOW_UP_REPLY,
        EmailCategory.RECRUITER_OUTREACH,
    }
)

_SYSTEM_PROMPT = """\
You are an email classifier for a job seeker's inbox monitor.
Your job is to classify incoming emails into job-search-relevant categories.

Categories:
- INTERVIEW_INVITE: Invitation to interview (phone screen, technical, onsite, etc.)
- OFFER: Job offer or salary negotiation communication
- REJECTION: Application rejection or "position filled" notification
- FOLLOW_UP_REPLY: Reply to a follow-up or outreach email the user previously sent
- RECRUITER_OUTREACH: Unsolicited recruiter message about a new opportunity
- APPLICATION_CONFIRMATION: Automated "we received your application" acknowledgement
- IRRELEVANT: Newsletters, promotions, spam, or anything not related to job search

Rules:
- Be conservative: if unsure, classify as IRRELEVANT
- requires_action should be True for categories where the user needs to respond or prepare
- urgency: "high" for interview invites and offers, "medium" for recruiter outreach and
  follow-up replies, "low" for confirmations, rejections, and irrelevant
- summary should be concise (under 100 chars) and mention the company if identifiable
- suggested_next_step should be a concrete action like "Reply to schedule interview"
"""


async def classify_email(
    *,
    subject: str,
    from_address: str,
    from_name: str,
    body_text: str,
    model: str | None = None,
    _model_override: Model | None = None,
) -> EmailClassification:
    """Classify a single email using the LLM.

    Parameters
    ----------
    subject, from_address, from_name, body_text:
        Email fields to classify.
    model:
        OpenRouter model string override. Defaults to ``INBOX_MODEL``.
    _model_override:
        Inject a Pydantic-AI ``Model`` for testing.
    """
    prompt = (
        f"From: {from_name} <{from_address}>\nSubject: {subject}\n\n{body_text[:3000]}"
    )

    result = await complete_structured(
        prompt,
        EmailClassification,
        system_prompt=_SYSTEM_PROMPT,
        model=model or INBOX_MODEL,
        _model_override=_model_override,
    )
    logger.debug(
        "Classified email from=%s subject=%r → %s (action=%s)",
        from_address,
        subject,
        result.category.value,
        result.requires_action,
    )
    return result
