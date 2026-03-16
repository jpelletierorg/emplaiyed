"""CV generation — tailors a candidate's profile for a specific opportunity."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from emplaiyed.core.models import Opportunity, Profile
from emplaiyed.generation.config import CV_SYSTEM_PROMPT
from emplaiyed.llm.config import CV_MODEL
from emplaiyed.llm.engine import complete_structured


class SkillCategory(BaseModel):
    category: str
    skills: list[str]


class CVExperience(BaseModel):
    company: str
    title: str
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)


class CVEducation(BaseModel):
    institution: str
    degree: str
    field: str
    start_date: str | None = None
    end_date: str | None = None


class CVCertification(BaseModel):
    name: str
    issuer: str
    date: str | None = None


class CVProject(BaseModel):
    name: str
    description: str
    url: str | None = None
    technologies: list[str] = Field(default_factory=list)


class GeneratedCV(BaseModel):
    name: str
    email: str
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    professional_title: str
    summary: str
    skill_categories: list[SkillCategory]
    experience: list[CVExperience]
    education: list[CVEducation]
    certifications: list[CVCertification] = Field(default_factory=list)
    projects: list[CVProject] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


def _build_cv_prompt(profile: Profile, opportunity: Opportunity, language: str) -> str:
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
            p for p in [profile.address.city, profile.address.province_state] if p
        ]
        if loc_parts:
            parts.append(f"Location: {', '.join(loc_parts)}")
    if profile.linkedin:
        parts.append(f"LinkedIn: {profile.linkedin}")
    if profile.github:
        parts.append(f"GitHub: {profile.github}")

    if profile.skills:
        parts.append(f"\nSkills: {', '.join(profile.skills)}")

    if profile.languages:
        langs = [f"{lang.language} ({lang.proficiency})" for lang in profile.languages]
        parts.append(f"Languages: {', '.join(langs)}")

    if profile.employment_history:
        parts.append("\n### Employment History")
        for emp in profile.employment_history:
            start = emp.start_date.isoformat() if emp.start_date else "?"
            end = emp.end_date.isoformat() if emp.end_date else "Present"
            parts.append(f"\n**{emp.title} at {emp.company}** ({start} – {end})")
            if emp.description:
                parts.append(f"{emp.description}")
            if emp.highlights:
                parts.append(
                    "Highlights (use these as raw material for CAR-format bullets):"
                )
                for h in emp.highlights:
                    parts.append(f"  • {h}")

    if profile.education:
        parts.append("\n### Education")
        for edu in profile.education:
            start = edu.start_date.isoformat() if edu.start_date else ""
            end = edu.end_date.isoformat() if edu.end_date else ""
            date_range = f" ({start} – {end})" if start or end else ""
            parts.append(
                f"- {edu.degree} in {edu.field}, {edu.institution}{date_range}"
            )

    if profile.certifications:
        parts.append("\n### Certifications")
        for cert in profile.certifications:
            date_str = cert.date_obtained.isoformat() if cert.date_obtained else ""
            expiry_str = (
                f" (expires {cert.expiry_date.isoformat()})" if cert.expiry_date else ""
            )
            parts.append(f"- {cert.name} ({cert.issuer}) {date_str}{expiry_str}")

    if profile.projects:
        parts.append("\n### Projects")
        for proj in profile.projects:
            tech_str = f" [{', '.join(proj.technologies)}]" if proj.technologies else ""
            url_str = f" ({proj.url})" if proj.url else ""
            parts.append(f"- {proj.name}{url_str}{tech_str}: {proj.description}")

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
            "Tailor and reorder all content to best match this specific job.",
            "Use 'Mon YYYY' format for all dates (e.g. 'Oct 2021').",
            f"CRITICAL: Write the ENTIRE CV in {language}. Every field — summary, "
            f"experience bullets, skill categories — must be in {language}.",
        ]
    )
    if profile.linkedin:
        parts.append(f"Include linkedin URL in output: {profile.linkedin}")
    if profile.github:
        parts.append(f"Include github URL in output: {profile.github}")

    return "\n".join(parts)


async def generate_cv(
    profile: Profile,
    opportunity: Opportunity,
    *,
    language: str,
    _model_override: Model | None = None,
) -> GeneratedCV:
    """Generate a tailored CV for the given opportunity."""
    prompt = _build_cv_prompt(profile, opportunity, language)
    return await complete_structured(
        prompt,
        GeneratedCV,
        system_prompt=CV_SYSTEM_PROMPT,
        model=CV_MODEL,
        _model_override=_model_override,
    )
