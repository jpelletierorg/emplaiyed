"""Render generated CV and letter to Markdown files."""

from __future__ import annotations

from pathlib import Path

from emplaiyed.generation.cv_generator import GeneratedCV
from emplaiyed.generation.letter_generator import GeneratedLetter


def render_cv_markdown(cv: GeneratedCV) -> str:
    """Render a GeneratedCV to a markdown string."""
    lines = [
        f"# {cv.name}",
        "",
        f"**{cv.professional_title}**",
        "",
    ]

    # Contact info
    contact = [cv.email]
    if cv.phone:
        contact.append(cv.phone)
    if cv.location:
        contact.append(cv.location)
    lines.append(" | ".join(contact))
    lines.append("")

    # Summary
    if cv.summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(cv.summary)
        lines.append("")

    # Skills (categorized)
    if cv.skill_categories:
        lines.append("## Skills")
        lines.append("")
        for cat in cv.skill_categories:
            lines.append(f"**{cat.category}:** {', '.join(cat.skills)}")
        lines.append("")

    # Experience
    if cv.experience:
        lines.append("## Experience")
        lines.append("")
        for exp in cv.experience:
            date_range = ""
            if exp.start_date or exp.end_date:
                start = exp.start_date or "?"
                end = exp.end_date or "Present"
                date_range = f" ({start} \u2013 {end})"
            lines.append(f"### {exp.title} \u2014 {exp.company}{date_range}")
            lines.append("")
            if exp.description:
                lines.append(exp.description)
                lines.append("")
            for h in exp.highlights:
                lines.append(f"- {h}")
            if exp.highlights:
                lines.append("")

    # Projects
    if cv.projects:
        lines.append("## Projects")
        lines.append("")
        for proj in cv.projects:
            url_str = f" ({proj.url})" if proj.url else ""
            lines.append(f"### {proj.name}{url_str}")
            lines.append("")
            lines.append(proj.description)
            lines.append("")
            if proj.technologies:
                lines.append(f"Technologies: {', '.join(proj.technologies)}")
                lines.append("")

    # Education (structured)
    if cv.education:
        lines.append("## Education")
        lines.append("")
        for edu in cv.education:
            date_range = ""
            if edu.start_date or edu.end_date:
                start = edu.start_date or "?"
                end = edu.end_date or "Present"
                date_range = f" ({start} \u2013 {end})"
            lines.append(
                f"- **{edu.degree} in {edu.field}**, {edu.institution}{date_range}"
            )
        lines.append("")

    # Certifications (structured)
    if cv.certifications:
        lines.append("## Certifications")
        lines.append("")
        for cert in cv.certifications:
            date_str = f" ({cert.date})" if cert.date else ""
            lines.append(f"- **{cert.name}** \u2014 {cert.issuer}{date_str}")
        lines.append("")

    # Languages
    if cv.languages:
        lines.append("## Languages")
        lines.append("")
        for lang in cv.languages:
            lines.append(f"- {lang}")
        lines.append("")

    return "\n".join(lines)


def render_letter_markdown(letter: GeneratedLetter) -> str:
    """Render a GeneratedLetter to a markdown string."""
    lines = [
        letter.greeting,
        "",
        letter.hook,
        "",
        letter.proof,
        "",
        letter.close,
        "",
        letter.closing,
        "",
        letter.signature_name,
    ]
    return "\n".join(lines)


def write_cv_markdown(cv: GeneratedCV, path: Path) -> None:
    """Render and write a CV markdown file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_cv_markdown(cv), encoding="utf-8")


def write_letter_markdown(letter: GeneratedLetter, path: Path) -> None:
    """Render and write a letter markdown file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_letter_markdown(letter), encoding="utf-8")
