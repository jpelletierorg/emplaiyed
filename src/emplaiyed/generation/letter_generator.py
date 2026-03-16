"""Motivation letter generation — writes a personalized letter per opportunity."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai.models import Model

from emplaiyed.core.models import Opportunity, Profile
from emplaiyed.core.prompt_helpers import format_recent_role, format_skills
from emplaiyed.generation.config import LETTER_SYSTEM_PROMPT
from emplaiyed.llm.config import LETTER_MODEL
from emplaiyed.llm.engine import complete_structured


class GeneratedLetter(BaseModel):
    greeting: str
    hook: str  # Paragraph 1: company's challenge + why it drives you
    proof: str  # Paragraph 2: relevant accomplishments with metrics
    close: str  # Paragraph 3: confident ask + what you'd contribute
    closing: str  # e.g. "Sincerely,"
    signature_name: str

    @property
    def body(self) -> str:
        """Combined body text for backward-compatible rendering."""
        return f"{self.hook}\n\n{self.proof}\n\n{self.close}"


def _build_letter_prompt(
    profile: Profile, opportunity: Opportunity, language: str
) -> str:
    """Build the user prompt for letter generation."""
    from datetime import date

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
        # Calculate approximate years of experience
        earliest = min(
            (e.start_date for e in profile.employment_history if e.start_date),
            default=None,
        )
        if earliest:
            years = (date.today() - earliest).days // 365
            parts.append(f"Years of professional experience: {years}")
        # Include top highlights from most recent roles (up to 5 total)
        parts.append("\nKey accomplishments:")
        highlight_count = 0
        for emp in profile.employment_history[:3]:
            for h in emp.highlights[:3]:
                if highlight_count >= 5:
                    break
                parts.append(f"  - ({emp.title} at {emp.company}) {h}")
                highlight_count += 1
            if highlight_count >= 5:
                break

    if profile.education:
        edu = profile.education[0]
        parts.append(f"\nEducation: {edu.degree} in {edu.field}, {edu.institution}")

    if profile.certifications:
        cert_names = [c.name for c in profile.certifications[:3]]
        parts.append(f"Certifications: {', '.join(cert_names)}")

    if profile.aspirations and profile.aspirations.statement:
        parts.append(f"Career goals: {profile.aspirations.statement}")

    parts.extend(
        [
            "",
            "## Target Job",
            f"Company: {opportunity.company}",
            f"Title: {opportunity.title}",
            f"Description: {opportunity.description}",
        ]
    )
    if opportunity.location:
        parts.append(f"Location: {opportunity.location}")

    parts.extend(
        [
            "",
            f"CRITICAL: Write ALL fields (greeting, body, closing) in {language}.",
        ]
    )

    return "\n".join(parts)


async def generate_letter(
    profile: Profile,
    opportunity: Opportunity,
    *,
    language: str,
    _model_override: Model | None = None,
) -> GeneratedLetter:
    """Generate a motivation letter for the given opportunity."""
    prompt = _build_letter_prompt(profile, opportunity, language)
    return await complete_structured(
        prompt,
        GeneratedLetter,
        system_prompt=LETTER_SYSTEM_PROMPT,
        model=LETTER_MODEL,
        _model_override=_model_override,
    )
