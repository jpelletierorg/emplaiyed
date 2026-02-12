"""Motivation letter generation — writes a personalized letter per opportunity."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai.models import Model

from emplaiyed.core.models import Opportunity, Profile
from emplaiyed.core.prompt_helpers import format_recent_role, format_skills
from emplaiyed.generation.config import LETTER_MODEL, LETTER_SYSTEM_PROMPT
from emplaiyed.llm.engine import complete_structured


class GeneratedLetter(BaseModel):
    greeting: str
    body: str
    closing: str
    signature_name: str


def _build_letter_prompt(profile: Profile, opportunity: Opportunity) -> str:
    """Build the user prompt for letter generation."""
    parts = [
        "Write a motivation letter for this candidate applying to this job.",
        "",
        "## Candidate",
        f"Name: {profile.name}",
    ]

    if profile.skills:
        parts.append(f"Key skills: {format_skills(profile)}")

    if profile.employment_history:
        parts.append(f"Current/recent role: {format_recent_role(profile)}")

    if profile.aspirations and profile.aspirations.statement:
        parts.append(f"Career goals: {profile.aspirations.statement}")

    parts.extend([
        "",
        "## Target Job",
        f"Company: {opportunity.company}",
        f"Title: {opportunity.title}",
        f"Description: {opportunity.description}",
    ])
    if opportunity.location:
        parts.append(f"Location: {opportunity.location}")

    return "\n".join(parts)


async def generate_letter(
    profile: Profile,
    opportunity: Opportunity,
    *,
    _model_override: Model | None = None,
) -> GeneratedLetter:
    """Generate a motivation letter for the given opportunity."""
    prompt = _build_letter_prompt(profile, opportunity)
    return await complete_structured(
        prompt,
        GeneratedLetter,
        system_prompt=LETTER_SYSTEM_PROMPT,
        model=LETTER_MODEL,
        _model_override=_model_override,
    )
