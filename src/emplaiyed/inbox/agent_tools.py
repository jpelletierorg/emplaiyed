"""Read-only email access for the browser agent.

Provides a single ``get_emails`` function that polls the IMAP inbox and
returns recent messages as structured data. The browser agent can use
the returned content to find verification codes, confirmation links,
or any other email-based information it needs during an apply run.

Design constraints:
- Read-only: IMAP folder is opened with ``readonly=True``.
- No send, no delete, no mark-as-read.
- Returns plain data; the model decides what to extract.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

from emplaiyed.inbox.config import ImapConfig, get_imap_config
from emplaiyed.inbox.fetcher import FetchedEmail, fetch_recent_emails

logger = logging.getLogger(__name__)


def _email_to_dict(em: FetchedEmail) -> dict:
    """Serialize a FetchedEmail to a plain dict for the agent."""
    return {
        "message_id": em.message_id,
        "from_address": em.from_address,
        "from_name": em.from_name,
        "to_address": em.to_address,
        "subject": em.subject,
        "date": em.date.isoformat() if em.date else None,
        "body_text": em.body_text,
        "headers": {
            "delivered_to": em.raw_headers.get("delivered-to", ""),
            "return_path": em.raw_headers.get("return-path", ""),
        },
    }


def _fetch_todays_emails(
    imap_config: ImapConfig, max_emails: int = 20
) -> list[FetchedEmail]:
    """Fetch emails from today (all, not just unread)."""
    from imapclient import IMAPClient

    since_date = date.today()

    logger.debug(
        "Connecting to %s:%d as %s",
        imap_config.host,
        imap_config.port,
        imap_config.user,
    )

    emails: list[FetchedEmail] = []
    try:
        with IMAPClient(imap_config.host, port=imap_config.port, ssl=True) as client:
            client.login(imap_config.user, imap_config.password)
            client.select_folder("INBOX", readonly=True)

            uids = client.search(["SINCE", since_date])
            if not uids:
                return []

            uids = uids[-max_emails:]
            raw_messages = client.fetch(uids, ["RFC822"])

            from emplaiyed.inbox.fetcher import _parse_message

            for uid, data in raw_messages.items():
                raw = data.get(b"RFC822")
                if not raw:
                    continue
                try:
                    parsed = _parse_message(raw)
                    emails.append(parsed)
                except Exception:
                    logger.warning("Failed to parse message UID %s", uid, exc_info=True)

    except Exception:
        logger.exception("IMAP fetch failed in get_emails")
        raise

    return emails


async def get_emails(
    *,
    waitfor: int = 120,
    max_emails: int = 20,
    imap_config: ImapConfig | None = None,
) -> str:
    """Fetch today's emails, polling up to ``waitfor`` seconds.

    Polls the IMAP inbox every 10 seconds until at least one email
    is found or the timeout expires. Returns a JSON string with
    the list of emails.

    Args:
        waitfor: Maximum seconds to poll. 0 means fetch once and return.
        max_emails: Maximum number of emails to return.
        imap_config: Override IMAP config (loaded from env if None).

    Returns:
        JSON string with ``{"found": bool, "count": int, "emails": [...]}``.
    """
    cfg = imap_config or get_imap_config()
    poll_interval = 10
    deadline = time.monotonic() + waitfor

    logger.info("get_emails: polling for up to %ds", waitfor)

    while True:
        try:
            emails = await asyncio.to_thread(_fetch_todays_emails, cfg, max_emails)
        except Exception as exc:
            logger.warning("get_emails: fetch error: %s", exc)
            emails = []

        if emails:
            logger.info("get_emails: found %d emails", len(emails))
            result = {
                "found": True,
                "count": len(emails),
                "emails": [_email_to_dict(em) for em in emails],
            }
            return json.dumps(result, ensure_ascii=False, indent=2)

        if time.monotonic() >= deadline:
            break

        remaining = deadline - time.monotonic()
        sleep_time = min(poll_interval, remaining)
        if sleep_time <= 0:
            break

        logger.debug("get_emails: no emails yet, sleeping %.0fs", sleep_time)
        await asyncio.sleep(sleep_time)

    logger.info("get_emails: timeout reached, no emails found")
    return json.dumps({"found": False, "count": 0, "emails": []})


async def check_imap_connection(imap_config: ImapConfig | None = None) -> bool:
    """Quick check that IMAP credentials work. Returns True on success."""
    cfg = imap_config or get_imap_config()

    def _check() -> bool:
        from imapclient import IMAPClient

        try:
            with IMAPClient(cfg.host, port=cfg.port, ssl=True) as client:
                client.login(cfg.user, cfg.password)
                client.select_folder("INBOX", readonly=True)
                logger.info("IMAP connection OK (host=%s, user=%s)", cfg.host, cfg.user)
                return True
        except Exception:
            logger.exception("IMAP connection failed")
            return False

    return await asyncio.to_thread(_check)
