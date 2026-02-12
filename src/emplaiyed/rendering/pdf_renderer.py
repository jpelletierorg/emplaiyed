"""Render generated CV and letter to PDF files using fpdf2."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from emplaiyed.generation.cv_generator import GeneratedCV
from emplaiyed.generation.letter_generator import GeneratedLetter

# Helvetica is Latin-1 only. Replace common Unicode characters.
_UNICODE_REPLACEMENTS = {
    "\u2014": "--",   # em-dash
    "\u2013": "-",    # en-dash
    "\u2018": "'",    # left single quote
    "\u2019": "'",    # right single quote
    "\u201c": '"',    # left double quote
    "\u201d": '"',    # right double quote
    "\u2026": "...",  # ellipsis
    "\u2022": "*",    # bullet
    "\u00a0": " ",    # non-breaking space
}


def _sanitize(text: str) -> str:
    """Replace Unicode characters unsupported by Helvetica with ASCII fallbacks."""
    for char, replacement in _UNICODE_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    return text


def _new_pdf() -> FPDF:
    """Create a new FPDF instance with standard settings."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    return pdf


def _add_heading(pdf: FPDF, text: str, size: int = 16) -> None:
    pdf.set_font("Helvetica", "B", size)
    pdf.cell(0, size * 0.6, _sanitize(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def _add_subheading(pdf: FPDF, text: str, size: int = 12) -> None:
    pdf.set_font("Helvetica", "B", size)
    pdf.cell(0, size * 0.5, _sanitize(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _add_text(pdf: FPDF, text: str, size: int = 10) -> None:
    pdf.set_font("Helvetica", "", size)
    pdf.multi_cell(0, size * 0.5, _sanitize(text))
    pdf.ln(1)


def _add_separator(pdf: FPDF) -> None:
    pdf.ln(2)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(3)


def render_cv_pdf(cv: GeneratedCV, path: Path) -> None:
    """Render a GeneratedCV to a PDF file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = _new_pdf()

    # Header
    _add_heading(pdf, cv.name, 18)
    _add_subheading(pdf, cv.professional_title, 13)

    # Contact
    contact_parts = [cv.email]
    if cv.phone:
        contact_parts.append(cv.phone)
    if cv.location:
        contact_parts.append(cv.location)
    _add_text(pdf, " | ".join(contact_parts))

    _add_separator(pdf)

    # Skills
    if cv.skills:
        _add_subheading(pdf, "Skills")
        _add_text(pdf, ", ".join(cv.skills))

    # Experience
    if cv.experience:
        _add_subheading(pdf, "Experience")
        for exp in cv.experience:
            date_range = ""
            if exp.start_date or exp.end_date:
                start = exp.start_date or "?"
                end = exp.end_date or "Present"
                date_range = f" ({start} - {end})"

            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 5, _sanitize(f"{exp.title} - {exp.company}{date_range}"),
                     new_x="LMARGIN", new_y="NEXT")

            if exp.description:
                _add_text(pdf, exp.description)
            for h in exp.highlights:
                _add_text(pdf, f"  * {h}")
            pdf.ln(1)

    # Education
    if cv.education:
        _add_subheading(pdf, "Education")
        for edu in cv.education:
            _add_text(pdf, f"  * {edu}")

    # Certifications
    if cv.certifications:
        _add_subheading(pdf, "Certifications")
        for cert in cv.certifications:
            _add_text(pdf, f"  * {cert}")

    # Languages
    if cv.languages:
        _add_subheading(pdf, "Languages")
        _add_text(pdf, ", ".join(cv.languages))

    pdf.output(str(path))


def render_letter_pdf(letter: GeneratedLetter, path: Path) -> None:
    """Render a GeneratedLetter to a PDF file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = _new_pdf()

    # Greeting
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, _sanitize(letter.greeting), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Body
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, _sanitize(letter.body))
    pdf.ln(6)

    # Closing
    pdf.cell(0, 7, _sanitize(letter.closing), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Signature
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _sanitize(letter.signature_name), new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(path))
