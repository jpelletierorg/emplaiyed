"""Navigate from a job posting URL to the actual application form.

Handles common patterns:
- Direct apply buttons on the posting page
- Redirects to external ATS portals (Greenhouse, Lever, Ashby)
- "Apply on company site" links
"""

from __future__ import annotations

import logging
import re

from emplaiyed.apply.browser import BrowserSession

logger = logging.getLogger(__name__)

# Common apply button selectors, ordered by specificity
_APPLY_SELECTORS = [
    # Explicit apply buttons/links
    'a[href*="apply"]',
    'button:has-text("Apply")',
    'a:has-text("Apply Now")',
    'a:has-text("Apply now")',
    'a:has-text("Postuler")',
    'a:has-text("Postuler maintenant")',
    'button:has-text("Apply Now")',
    'button:has-text("Apply now")',
    'button:has-text("Postuler")',
    # Job board specific
    'a[data-action="apply"]',
    "a.apply-button",
    "button.apply-button",
    "#apply-button",
    ".job-apply a",
    ".apply-btn",
]

# Patterns that indicate we've already landed on an application form
_FORM_INDICATORS = [
    'form[action*="apply"]',
    'form[action*="submit"]',
    'form[action*="application"]',
    "#application-form",
    ".application-form",
    'input[name="resume"]',
    'input[type="file"]',
    'input[name="first_name"]',
    'input[name="name"]',
]


async def navigate_to_apply_page(
    session: BrowserSession, source_url: str
) -> str | None:
    """Navigate from the job posting to the application form.

    Returns the URL of the application page, or None if no apply entry point
    was found.
    """
    await session.goto(source_url)
    await session.screenshot("01_posting_page.png")

    # Check if we're already on an application form
    for selector in _FORM_INDICATORS:
        el = await session.query_selector(selector)
        if el:
            logger.info("Already on application form: %s", session.url)
            return session.url

    # Try to find and click an apply button
    for selector in _APPLY_SELECTORS:
        try:
            el = await session.query_selector(selector)
            if el:
                is_visible = await el.is_visible()
                if not is_visible:
                    continue

                # If it's a link, check href first
                href = await el.get_attribute("href")
                if href and _is_external_apply_link(href):
                    logger.info("Following external apply link: %s", href)
                    await session.goto(href)
                    await session.screenshot("02_apply_redirect.png")
                    return session.url

                # Click and wait for navigation
                await el.click()
                # Wait briefly for navigation or popup
                try:
                    await session.page.wait_for_load_state(
                        "domcontentloaded", timeout=5000
                    )
                except Exception:
                    pass

                await session.screenshot("02_after_apply_click.png")

                # Check if a new page/tab opened
                pages = session._context.pages
                if len(pages) > 1:
                    # Switch to the new page
                    new_page = pages[-1]
                    session._page = new_page
                    await new_page.wait_for_load_state("domcontentloaded")
                    await session.screenshot("02_new_tab.png")

                logger.info("Navigated to apply page: %s", session.url)
                return session.url
        except Exception as exc:
            logger.debug("Selector %s failed: %s", selector, exc)
            continue

    logger.warning("No apply entry point found on %s", source_url)
    return None


def _is_external_apply_link(href: str) -> bool:
    """Check if a link points to an external ATS or application page."""
    patterns = [
        r"boards\.greenhouse\.io",
        r"jobs\.greenhouse\.io",
        r"jobs\.lever\.co",
        r"jobs\.ashbyhq\.com",
        r"apply\.workday\.com",
        r"careers\.",
        r"/apply",
        r"/application",
    ]
    return any(re.search(p, href, re.IGNORECASE) for p in patterns)
