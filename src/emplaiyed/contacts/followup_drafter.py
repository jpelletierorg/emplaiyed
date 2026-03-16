"""Contact-aware follow-up content generation.

Generates personalized follow-up messages that reference the specific
contact person, their role, and the application history.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.models import Application, Contact, Opportunity, Profile
from emplaiyed.llm.engine import complete_structured

logger = logging.getLogger(__name__)


class FollowUpContent(BaseModel):
    """Generated follow-up content for a specific contact."""

    subject: str = Field(description="Email subject line")
    body: str = Field(description="Full email body text")
    channel_suggestion: str = Field(
        description="Recommended channel: 'email', 'linkedin', or 'phone'"
    )
    tone_note: str = Field(
        description="Brief note about the tone/approach chosen and why"
    )


_FOLLOWUP_SYSTEM_PROMPT = """\
You write follow-up messages for job applications. Your messages are:
- Professional but warm -- you're a real person, not a template
- Brief -- under 100 words for the body
- Specific -- reference the role, company, and something concrete
- Non-pushy -- express continued interest without demanding a response
- Channel-aware -- suggest the best way to reach this person

If the contact is a recruiter, be direct and professional.
If the contact is a hiring manager, reference something technical.
If no contact name is known, use "Dear Hiring Team" or similar.

CRITICAL: Write in the same language as the job description. If the job is in \
French, write the follow-up in French.
"""


def _build_followup_prompt(
    profile: Profile,
    opportunity: Opportunity,
    contact: Contact | None,
    application: Application,
    followup_number: int,
    days_since: int,
) -> str:
    """Build the prompt for follow-up content generation."""
    parts = [
        "Generate a follow-up message for this job application.",
        "",
        "## Context",
        f"Candidate: {profile.name}",
        f"Company: {opportunity.company}",
        f"Role: {opportunity.title}",
        f"Days since last contact: {days_since}",
        f"Follow-up number: {followup_number} "
        f"({'first' if followup_number == 1 else 'second and final'})",
    ]

    if contact:
        parts.append("\n## Contact Person")
        if contact.name:
            parts.append(f"Name: {contact.name}")
        if contact.title:
            parts.append(f"Role: {contact.title}")
        if contact.email:
            parts.append(f"Email: {contact.email}")
        if contact.phone:
            parts.append(f"Phone: {contact.phone}")
    else:
        parts.append("\n## Contact Person")
        parts.append("No specific contact identified. Address to hiring team.")

    if profile.skills:
        parts.append(f"\nCandidate skills: {', '.join(profile.skills[:8])}")

    if profile.aspirations and profile.aspirations.statement:
        parts.append(f"Career focus: {profile.aspirations.statement}")

    # Include a snippet of the job description for context
    desc_snippet = opportunity.description[:500] if opportunity.description else ""
    if desc_snippet:
        parts.append("\n## Job Description (snippet)")
        parts.append(desc_snippet)

    if followup_number == 2:
        parts.append(
            "\nIMPORTANT: This is the FINAL follow-up. Make it count but keep it "
            "graceful -- leave the door open without being desperate."
        )

    return "\n".join(parts)


async def draft_contact_followup(
    profile: Profile,
    opportunity: Opportunity,
    application: Application,
    contact: Contact | None,
    *,
    followup_number: int = 1,
    days_since: int = 5,
    _model_override: Model | None = None,
) -> FollowUpContent:
    """Generate a personalized follow-up for a specific contact.

    Parameters
    ----------
    profile: Candidate profile.
    opportunity: The job opportunity.
    application: The application being followed up on.
    contact: The contact person (or None for generic follow-up).
    followup_number: 1 for first follow-up, 2 for second.
    days_since: Days since last contact.
    _model_override: Inject TestModel for tests.
    """
    from emplaiyed.llm.config import OUTREACH_MODEL

    prompt = _build_followup_prompt(
        profile,
        opportunity,
        contact,
        application,
        followup_number,
        days_since,
    )

    return await complete_structured(
        prompt,
        FollowUpContent,
        system_prompt=_FOLLOWUP_SYSTEM_PROMPT,
        model=OUTREACH_MODEL,
        _model_override=_model_override,
    )
