"""Detect which portal/ATS an application page belongs to.

Inspects the URL and page content to determine if the page is a known
ATS (Greenhouse, Lever, Ashby) or a generic form.
"""

from __future__ import annotations

import logging
import re

from emplaiyed.apply.browser import BrowserSession
from emplaiyed.core.models import PortalKind

logger = logging.getLogger(__name__)

# URL-based detection patterns
_URL_PATTERNS: list[tuple[str, PortalKind]] = [
    (r"boards\.greenhouse\.io", PortalKind.GREENHOUSE),
    (r"jobs\.greenhouse\.io", PortalKind.GREENHOUSE),
    (r"greenhouse\.io", PortalKind.GREENHOUSE),
    (r"jobs\.lever\.co", PortalKind.LEVER),
    (r"lever\.co", PortalKind.LEVER),
    (r"jobs\.ashbyhq\.com", PortalKind.ASHBY),
    (r"ashbyhq\.com", PortalKind.ASHBY),
]

# DOM-based detection selectors
_DOM_INDICATORS: list[tuple[str, PortalKind]] = [
    ("#grnhse_app", PortalKind.GREENHOUSE),
    ('[data-app="greenhouse"]', PortalKind.GREENHOUSE),
    (".lever-application-form", PortalKind.LEVER),
    ('[class*="lever-"]', PortalKind.LEVER),
    ('[data-testid*="ashby"]', PortalKind.ASHBY),
    (".ashby-job-posting", PortalKind.ASHBY),
]


async def detect_portal(session: BrowserSession) -> PortalKind:
    """Detect the portal type from the current page.

    Checks URL patterns first (fast), then falls back to DOM inspection.
    Returns PortalKind.GENERIC if the page has a form but is not a known ATS.
    Returns PortalKind.UNKNOWN if no form is detected at all.
    """
    url = session.url

    # URL-based detection
    for pattern, kind in _URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            logger.info("Detected portal %s from URL: %s", kind.value, url)
            return kind

    # DOM-based detection
    for selector, kind in _DOM_INDICATORS:
        try:
            el = await session.query_selector(selector)
            if el:
                logger.info(
                    "Detected portal %s from DOM selector: %s", kind.value, selector
                )
                return kind
        except Exception:
            continue

    # Check if there's any form at all
    form = await session.query_selector("form")
    if form:
        logger.info("Detected generic form on %s", url)
        return PortalKind.GENERIC

    logger.warning("No recognizable portal or form detected on %s", url)
    return PortalKind.UNKNOWN
