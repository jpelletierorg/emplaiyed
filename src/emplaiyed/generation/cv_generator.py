"""CV generation — tailors a candidate's profile for a specific opportunity."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.models import Opportunity, Profile
from emplaiyed.generation.config import CV_MODEL, CV_SYSTEM_PROMPT
from emplaiyed.llm.engine import complete_structured


class CVExperience(BaseModel):
    company: str
    title: str
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)


class GeneratedCV(BaseModel):
    name: str
    email: str
    phone: str | None = None
    location: str | None = None
    professional_title: str
    skills: list[str]
    experience: list[CVExperience]
    education: list[str]
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


def _build_cv_prompt(profile: Profile, opportunity: Opportunity) -> str:
    """Build the user prompt for CV generation."""
    parts = [
        "Generate a tailored CV for this candidate and job opportunity.",
        "",
        "## Candidate Profile",
        f"Name: {profile.name}",
        f"Email: {profile.email}",
    ]
    if profile.phone:
        parts.append(f"Phone: {profile.phone}")
    if profile.address:
        loc_parts = [
            p for p in [profile.address.city, profile.address.province_state]
            if p
        ]
        if loc_parts:
            parts.append(f"Location: {', '.join(loc_parts)}")

    if profile.skills:
        parts.append(f"\nSkills: {', '.join(profile.skills)}")

    if profile.languages:
        langs = [f"{l.language} ({l.proficiency})" for l in profile.languages]
        parts.append(f"Languages: {', '.join(langs)}")

    if profile.employment_history:
        parts.append("\n### Employment History")
        for emp in profile.employment_history:
            start = emp.start_date.isoformat() if emp.start_date else "?"
            end = emp.end_date.isoformat() if emp.end_date else "Present"
            parts.append(f"- {emp.title} at {emp.company} ({start} – {end})")
            if emp.description:
                parts.append(f"  {emp.description}")
            for h in emp.highlights:
                parts.append(f"  • {h}")

    if profile.education:
        parts.append("\n### Education")
        for edu in profile.education:
            parts.append(f"- {edu.degree} in {edu.field}, {edu.institution}")

    if profile.certifications:
        parts.append("\n### Certifications")
        for cert in profile.certifications:
            date_str = cert.date_obtained.isoformat() if cert.date_obtained else ""
            parts.append(f"- {cert.name} ({cert.issuer}) {date_str}")

    parts.extend([
        "",
        "## Target Job",
        f"Company: {opportunity.company}",
        f"Title: {opportunity.title}",
        f"Description: {opportunity.description}",
    ])
    if opportunity.location:
        parts.append(f"Location: {opportunity.location}")

    parts.extend([
        "",
        "Reorder and select content to best match this specific job.",
    ])
    return "\n".join(parts)


async def generate_cv(
    profile: Profile,
    opportunity: Opportunity,
    *,
    _model_override: Model | None = None,
) -> GeneratedCV:
    """Generate a tailored CV for the given opportunity."""
    prompt = _build_cv_prompt(profile, opportunity)
    return await complete_structured(
        prompt,
        GeneratedCV,
        system_prompt=CV_SYSTEM_PROMPT,
        model=CV_MODEL,
        _model_override=_model_override,
    )
