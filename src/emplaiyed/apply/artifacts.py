"""Evidence capture for apply runs.

Captures screenshots, HTML snapshots, and confirmation text to prove
that an application was (or was not) successfully submitted.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from emplaiyed.apply.browser import BrowserSession

logger = logging.getLogger(__name__)

# Patterns that indicate successful submission
_CONFIRMATION_PATTERNS = [
    r"application\s+(has\s+been\s+)?(received|submitted|sent)",
    r"thank\s+you\s+for\s+(applying|your\s+application)",
    r"merci\s+(pour\s+votre\s+candidature|d'avoir\s+postul)",
    r"candidature\s+(a\s+bien\s+ete\s+)?((envoy|soumise|re[çc]ue))",
    r"successfully\s+(submitted|applied)",
    r"we('ve|\s+have)\s+received\s+your",
    r"your\s+application\s+is\s+complete",
]


@dataclass
class SubmissionEvidence:
    """Evidence collected after attempting to submit an application."""

    confirmed: bool
    confirmation_text: str | None = None
    final_url: str | None = None
    screenshot_path: Path | None = None
    html_path: Path | None = None


async def capture_submission_evidence(session: BrowserSession) -> SubmissionEvidence:
    """Capture evidence after clicking submit.

    Takes a screenshot, saves the HTML, and checks for confirmation text.
    """
    screenshot_path = await session.screenshot("confirmation.png")
    html_path = await session.save_html("confirmation.html")

    page_text = await session.evaluate("() => document.body.innerText")
    confirmation = _find_confirmation(page_text)

    return SubmissionEvidence(
        confirmed=confirmation is not None,
        confirmation_text=confirmation,
        final_url=session.url,
        screenshot_path=screenshot_path,
        html_path=html_path,
    )


def _find_confirmation(text: str) -> str | None:
    """Search page text for confirmation patterns."""
    text_lower = text.lower()
    for pattern in _CONFIRMATION_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            # Extract a meaningful snippet around the match
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 80)
            snippet = text[start:end].strip()
            logger.info("Confirmation found: %s", snippet)
            return snippet
    return None
