"""Email-to-application matcher.

Matches an incoming email to an existing application using the
plus-address tag embedded in the ``To`` header.

The user applies to jobs using ``moi+<short_id>@jpelletier.org``.
When the company replies, the plus-tag is preserved, giving us a
deterministic link back to the opportunity.

If the email has no plus-tag (or the tag doesn't match any tracked
opportunity), we return None. Classification of the email content
(interview invite, rejection, follow-up reply, etc.) is handled
entirely by the LLM classifier — not by heuristics in the matcher.
"""

from __future__ import annotations

import logging
import re
import sqlite3

from emplaiyed.core.database import (
    get_opportunity_by_short_id,
    list_applications,
)
from emplaiyed.core.models import Application, Opportunity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plus-address tag extraction
# ---------------------------------------------------------------------------

_PLUS_TAG_RE = re.compile(r"\+([A-Za-z0-9]{4,10})@")


def _extract_plus_tag(to_address: str) -> str | None:
    """Extract the plus-address tag from a To address.

    ``moi+r8dZcf@jpelletier.org`` → ``r8dZcf``
    """
    m = _PLUS_TAG_RE.search(to_address)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class MatchResult:
    """Result of matching an email to an application."""

    __slots__ = ("application", "opportunity", "match_tier")

    def __init__(
        self,
        application: Application,
        opportunity: Opportunity,
        match_tier: str,
    ):
        self.application = application
        self.opportunity = opportunity
        self.match_tier = match_tier

    def __repr__(self) -> str:
        return (
            f"MatchResult(app={self.application.id[:8]}, "
            f"company={self.opportunity.company!r}, tier={self.match_tier!r})"
        )


def match_email_to_application(
    conn: sqlite3.Connection,
    *,
    to_address: str = "",
) -> MatchResult | None:
    """Try to match an email to an existing application via plus-tag.

    Returns a MatchResult with the matched application and opportunity,
    or None if the email has no plus-tag or the tag doesn't match.
    """
    tag = _extract_plus_tag(to_address)
    if not tag:
        logger.debug("No plus-tag in to_address=%s", to_address)
        return None

    opp = get_opportunity_by_short_id(conn, tag)
    if not opp:
        logger.debug("Plus-tag +%s does not match any opportunity", tag)
        return None

    apps = list_applications(conn, opportunity_id=opp.id)
    if not apps:
        logger.debug(
            "Plus-tag +%s matched opp %s (%s) but no application found",
            tag,
            opp.id[:8],
            opp.company,
        )
        return None

    logger.debug(
        "Plus-tag match: +%s → %s (%s)",
        tag,
        opp.company,
        apps[0].id[:8],
    )
    return MatchResult(apps[0], opp, "plus_tag")
