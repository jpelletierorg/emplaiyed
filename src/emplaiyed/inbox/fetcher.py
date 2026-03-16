"""IMAP email fetcher — connects to the mail server and retrieves messages.

Uses IMAPClient for a clean Pythonic IMAP interface and stdlib ``email``
for MIME parsing.  HTML bodies are converted to plain text via html2text.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import html2text
from imapclient import IMAPClient

from emplaiyed.inbox.config import ImapConfig

logger = logging.getLogger(__name__)

_h2t = html2text.HTML2Text()
_h2t.ignore_links = False
_h2t.ignore_images = True
_h2t.body_width = 0  # no wrapping


@dataclass
class FetchedEmail:
    """A single parsed email message."""

    message_id: str
    from_address: str
    from_name: str
    to_address: str
    subject: str
    date: datetime | None
    body_text: str
    raw_headers: dict = field(default_factory=dict)


def _decode_header(raw: str | None) -> str:
    """Decode an RFC 2047 encoded header into a plain string."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded: list[str] = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_body(msg: email.message.Message) -> str:
    """Extract the best text body from a MIME message."""
    # Prefer text/plain, fall back to text/html -> markdown
    if msg.is_multipart():
        text_parts: list[str] = []
        html_parts: list[str] = []
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    text_parts.append(payload.decode(charset, errors="replace"))
            elif ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html_parts.append(payload.decode(charset, errors="replace"))
        if text_parts:
            return "\n".join(text_parts)
        if html_parts:
            return _h2t.handle("\n".join(html_parts)).strip()
        return ""
    else:
        ct = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if not payload:
            return ""
        charset = msg.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if ct == "text/html":
            return _h2t.handle(text).strip()
        return text


def _parse_message(raw_bytes: bytes) -> FetchedEmail:
    """Parse raw RFC 822 bytes into a FetchedEmail."""
    msg = email.message_from_bytes(raw_bytes)

    message_id = msg.get("Message-ID", "")
    from_raw = msg.get("From", "")
    from_name, from_addr = email.utils.parseaddr(from_raw)
    to_raw = msg.get("To", "")
    _, to_addr = email.utils.parseaddr(to_raw)
    subject = _decode_header(msg.get("Subject"))

    date_str = msg.get("Date")
    msg_date = None
    if date_str:
        parsed = email.utils.parsedate_to_datetime(date_str)
        if parsed:
            msg_date = parsed

    body = _extract_body(msg)
    # Truncate very long bodies to save LLM tokens
    if len(body) > 4000:
        body = body[:4000] + "\n\n[... truncated]"

    return FetchedEmail(
        message_id=message_id.strip(),
        from_address=from_addr,
        from_name=_decode_header(from_name) or from_addr,
        to_address=to_addr,
        subject=subject,
        date=msg_date,
        body_text=body,
        raw_headers={
            "from": from_raw,
            "to": to_raw,
            "reply-to": msg.get("Reply-To", ""),
        },
    )


def fetch_recent_emails(
    config: ImapConfig,
    *,
    since_days: int = 1,
    folder: str = "INBOX",
    max_emails: int = 100,
) -> list[FetchedEmail]:
    """Connect to IMAP and fetch emails from the last ``since_days`` days.

    Only fetches UNSEEN messages by default.  Does NOT mark them as read.
    """
    since_date = date.today() - timedelta(days=since_days)

    logger.debug("Connecting to %s:%d as %s", config.host, config.port, config.user)

    emails: list[FetchedEmail] = []

    try:
        with IMAPClient(config.host, port=config.port, ssl=True) as client:
            client.login(config.user, config.password)
            client.select_folder(folder, readonly=True)

            # Search for recent unseen messages
            uids = client.search(["SINCE", since_date, "UNSEEN"])
            if not uids:
                logger.debug("No unseen messages since %s", since_date)
                return []

            # Limit to most recent N
            uids = uids[-max_emails:]
            logger.debug("Fetching %d messages", len(uids))

            raw_messages = client.fetch(uids, ["RFC822"])

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
        logger.exception("IMAP fetch failed")
        raise

    logger.debug("Fetched %d emails", len(emails))
    return emails
