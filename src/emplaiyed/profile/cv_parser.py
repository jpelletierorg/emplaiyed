"""CV Parser — extracts text from a PDF/text file and uses the LLM to
produce a partial Profile.

The module is intentionally simple: pdfminer.six for text extraction,
then a single structured LLM call to parse the text into our Profile model.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pdfminer.high_level import extract_text as pdf_extract_text
from pydantic_ai.models import Model

logger = logging.getLogger(__name__)

from emplaiyed.core.models import Profile
from emplaiyed.llm.engine import complete_structured

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(file_path: Path) -> str:
    """Extract raw text from a file.

    Supports PDF files (via pdfminer.six) and plain text files.
    Raises ``ValueError`` if the file does not exist or yields no text.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    logger.debug("Extracting text from %s (type=%s)", file_path, suffix)

    if suffix == ".pdf":
        text = pdf_extract_text(str(file_path))
    else:
        # Assume plain text for everything else (.txt, .md, etc.)
        text = file_path.read_text(encoding="utf-8")

    text = text.strip()
    if not text:
        raise ValueError(f"No text could be extracted from: {file_path}")

    return text


# ---------------------------------------------------------------------------
# LLM parsing
# ---------------------------------------------------------------------------

_CV_PARSE_PROMPT = """\
You are a professional CV/resume parser. Extract structured information from
the following CV text and return it as a JSON object matching the Profile
schema.

Rules:
- Extract every piece of information you can find.
- For fields you cannot find, use null (for optional scalars) or empty lists.
- name and email are required — infer them if possible, use "Unknown" / \
"unknown@example.com" only as a last resort.
- For dates, use ISO format (YYYY-MM-DD). If only a year is given, use \
January 1st of that year. If year and month, use the 1st of that month.
- Skills should be a flat list of technology/skill names.
- Do NOT fabricate information that is not in the CV.

IMPORTANT — the Profile schema does NOT have a "summary" field. Do not \
attempt to store the CV summary. The summary section in a CV is a generated \
artifact tailored to a specific job — it is not a fact about the person.

IMPORTANT — Certifications have BOTH date_obtained AND expiry_date fields. \
CVs often show certification date ranges like "2019 - 2022". Parse the first \
date as date_obtained and the second as expiry_date. Use January 1st if only \
a year is given.

IMPORTANT — Employment history: extract each position's bullet points as \
highlights. Capture the actual text from the CV.

IMPORTANT — work_arrangement in aspirations is a list of strings (e.g. \
["remote", "hybrid", "on-site"]). Leave it as an empty list since CVs \
typically don't state work arrangement preferences.

CV text:
---
{cv_text}
---
"""


async def parse_cv(
    file_path: Path,
    *,
    _model_override: Model | None = None,
) -> Profile:
    """Parse a CV file and return a partial Profile.

    Parameters
    ----------
    file_path:
        Path to the CV file (PDF or plain text).
    _model_override:
        Inject a Pydantic-AI ``Model`` for testing (avoids real API calls).
    """
    cv_text = extract_text(file_path)
    return await parse_cv_text(cv_text, _model_override=_model_override)


async def parse_cv_text(
    cv_text: str,
    *,
    _model_override: Model | None = None,
) -> Profile:
    """Parse raw CV text into a Profile using the LLM.

    Useful when the text has already been extracted (e.g. pasted by user).
    """
    prompt = _CV_PARSE_PROMPT.format(cv_text=cv_text)
    return await complete_structured(
        prompt,
        output_type=Profile,
        _model_override=_model_override,
    )
