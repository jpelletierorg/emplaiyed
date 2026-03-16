"""Render generated CV and letter to PDF via HTML/CSS templates (Jinja2 + WeasyPrint)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import jinja2

from emplaiyed.core.models import Profile
from emplaiyed.generation.cv_generator import GeneratedCV
from emplaiyed.generation.letter_generator import GeneratedLetter

# WeasyPrint uses cffi to dlopen system libraries (pango, glib).
# On macOS with Homebrew, these live under /opt/homebrew/lib which isn't
# on the default dlopen search path. Ensure it's discoverable.
if sys.platform == "darwin":
    _brew_lib = "/opt/homebrew/lib"
    _current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if _brew_lib not in _current:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
            f"{_brew_lib}:{_current}" if _current else _brew_lib
        )

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _format_date(value: str | None, default: str = "") -> str:
    """Convert ISO-ish date strings to human-readable format.

    Handles: "2021-10-15" → "Oct 2021", "2021-10" → "Oct 2021",
    "2021" → "2021", "Present" → "Present", None → default.
    """
    if not value:
        return default
    if value.lower() == "present":
        return "Present"
    parts = value.split("-")
    if len(parts) >= 2:
        try:
            from datetime import date

            year, month = int(parts[0]), int(parts[1])
            return date(year, month, 1).strftime("%b %Y")
        except (ValueError, IndexError):
            return value
    return value


_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)
_ENV.filters["format_date"] = _format_date


def render_cv_html(cv: GeneratedCV) -> str:
    """Render a GeneratedCV to an HTML string."""
    template = _ENV.get_template("cv.html")
    return template.render(cv=cv)


def render_cv_pdf(cv: GeneratedCV, path: Path) -> None:
    """Render a GeneratedCV to a PDF file via HTML."""
    import weasyprint

    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_cv_html(cv)
    weasyprint.HTML(string=html).write_pdf(str(path))


def render_letter_html(
    letter: GeneratedLetter,
    profile: Profile | None = None,
) -> str:
    """Render a GeneratedLetter to an HTML string."""
    from datetime import datetime

    template = _ENV.get_template("letter.html")
    today_date = datetime.now().strftime("%B %d, %Y")
    return template.render(letter=letter, profile=profile, today_date=today_date)


def render_letter_pdf(
    letter: GeneratedLetter,
    path: Path,
    profile: Profile | None = None,
) -> None:
    """Render a GeneratedLetter to a PDF file via HTML."""
    import weasyprint

    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_letter_html(letter, profile=profile)
    weasyprint.HTML(string=html).write_pdf(str(path))
