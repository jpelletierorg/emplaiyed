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

    # Skills
    if cv.skills:
        lines.append("## Skills")
        lines.append("")
        lines.append(", ".join(cv.skills))
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
                date_range = f" ({start} – {end})"
            lines.append(f"### {exp.title} — {exp.company}{date_range}")
            lines.append("")
            if exp.description:
                lines.append(exp.description)
                lines.append("")
            for h in exp.highlights:
                lines.append(f"- {h}")
            if exp.highlights:
                lines.append("")

    # Education
    if cv.education:
        lines.append("## Education")
        lines.append("")
        for edu in cv.education:
            lines.append(f"- {edu}")
        lines.append("")

    # Certifications
    if cv.certifications:
        lines.append("## Certifications")
        lines.append("")
        for cert in cv.certifications:
            lines.append(f"- {cert}")
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
        letter.body,
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
