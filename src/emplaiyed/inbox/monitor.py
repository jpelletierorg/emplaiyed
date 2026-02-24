"""Inbox monitor orchestrator.

Fetch → deduplicate → classify → match → record → notify.

This is the main entry-point called by ``emplaiyed inbox check``.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from pydantic_ai.models import Model

from emplaiyed.core.database import (
    is_email_processed,
    save_interaction,
    save_processed_email,
    save_work_item,
)
from emplaiyed.core.models import (
    ApplicationStatus,
    Interaction,
    InteractionType,
    WorkItem,
    WorkStatus,
    WorkType,
)
from emplaiyed.inbox.classifier import (
    ACTIONABLE_CATEGORIES,
    EmailClassification,
    classify_email,
)
from emplaiyed.inbox.config import (
    ImapConfig,
    TelegramConfig,
    get_imap_config,
    get_telegram_config,
)
from emplaiyed.inbox.fetcher import FetchedEmail, fetch_recent_emails
from emplaiyed.inbox.matcher import MatchResult, match_email_to_application
from emplaiyed.inbox.notifier import send_telegram_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class ProcessedEmail:
    """One email that went through the full pipeline."""

    email: FetchedEmail
    classification: EmailClassification
    match: MatchResult | None
    work_item_id: str | None = None


@dataclass
class MonitorResult:
    """Summary of an inbox check run."""

    total_fetched: int = 0
    already_processed: int = 0
    classified: int = 0
    matched: int = 0
    work_items_created: int = 0
    notification_sent: bool = False
    processed: list[ProcessedEmail] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Telegram briefing formatter
# ---------------------------------------------------------------------------

_URGENCY_EMOJI = {
    "high": "\U0001f534",  # red circle
    "medium": "\U0001f7e1",  # yellow circle
    "low": "\u26aa",  # white circle
}


def _format_briefing(processed: list[ProcessedEmail]) -> str:
    """Build a Telegram-friendly morning briefing message."""
    if not processed:
        return "\u2705 *Inbox Check*\nNo new job-related emails."

    lines: list[str] = ["\U0001f4ec *Inbox Briefing*\n"]

    actionable = [p for p in processed if p.classification.requires_action]
    informational = [p for p in processed if not p.classification.requires_action]

    if actionable:
        lines.append("*Action Required:*")
        for p in actionable:
            emoji = _URGENCY_EMOJI.get(p.classification.urgency, "\u26aa")
            company = ""
            if p.match:
                company = f" ({p.match.opportunity.company})"
            lines.append(f"{emoji} {p.classification.summary}{company}")
            if p.classification.suggested_next_step:
                lines.append(f"   \u2192 {p.classification.suggested_next_step}")
        lines.append("")

    if informational:
        lines.append("*FYI:*")
        for p in informational:
            cat = p.classification.category.value.replace("_", " ").title()
            lines.append(f"\u26aa {cat}: {p.classification.summary}")
        lines.append("")

    # Footer
    lines.append(
        f"_Total: {len(processed)} emails "
        f"({len(actionable)} actionable, {len(informational)} info)_"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


async def run_inbox_check(
    conn: sqlite3.Connection,
    *,
    imap_config: ImapConfig | None = None,
    telegram_config: TelegramConfig | None = None,
    since_days: int = 1,
    dry_run: bool = False,
    _model_override: Model | None = None,
) -> MonitorResult:
    """Run a full inbox check cycle.

    Parameters
    ----------
    conn:
        Database connection (must already have processed_emails table).
    imap_config / telegram_config:
        Override configs (loaded from env if None).
    since_days:
        How many days back to fetch.
    dry_run:
        If True, classify + match but do NOT record to DB or send Telegram.
    _model_override:
        Inject a test model for the classifier.
    """
    result = MonitorResult()
    run_start = time.monotonic()
    logger.info(
        "=== Inbox check started (since_days=%d, dry_run=%s) ===", since_days, dry_run
    )

    # 1. Fetch emails
    try:
        imap_cfg = imap_config or get_imap_config()
    except RuntimeError:
        logger.error(
            "IMAP credentials not configured — cannot fetch emails. "
            "Set EMPLAIYED_IMAP_HOST, EMPLAIYED_IMAP_USER, "
            "EMPLAIYED_IMAP_PASSWORD in .env"
        )
        raise

    try:
        emails = fetch_recent_emails(imap_cfg, since_days=since_days)
    except Exception:
        logger.exception("IMAP fetch failed")
        raise

    result.total_fetched = len(emails)
    logger.info(
        "Fetched %d emails from IMAP (host=%s, user=%s)",
        len(emails),
        imap_cfg.host,
        imap_cfg.user,
    )

    if not emails:
        # Still send a "nothing new" briefing
        logger.info("No emails found — sending empty briefing")
        if not dry_run:
            tg_cfg = telegram_config or _safe_get_telegram_config()
            if tg_cfg:
                result.notification_sent = await send_telegram_message(
                    tg_cfg, _format_briefing([])
                )
            else:
                logger.error("Telegram not configured — cannot send briefing")
        _log_run_summary(result, run_start)
        return result

    # 2. Deduplicate against processed_emails
    new_emails: list[FetchedEmail] = []
    for em in emails:
        if not em.message_id:
            new_emails.append(em)
            continue
        if is_email_processed(conn, em.message_id):
            result.already_processed += 1
        else:
            new_emails.append(em)

    logger.info(
        "%d new emails (%d already processed)",
        len(new_emails),
        result.already_processed,
    )

    # 3. Classify + match each email
    for em in new_emails:
        try:
            classification = await classify_email(
                subject=em.subject,
                from_address=em.from_address,
                from_name=em.from_name,
                body_text=em.body_text,
                _model_override=_model_override,
            )
        except Exception as exc:
            logger.warning("Failed to classify email %s: %s", em.message_id, exc)
            result.errors.append(f"Classify error ({em.subject[:40]}): {exc}")
            continue

        result.classified += 1
        logger.info(
            "Classified email from=%s subject='%s' -> category=%s urgency=%s action=%s",
            em.from_address,
            em.subject[:60],
            classification.category.value,
            classification.urgency,
            classification.requires_action,
        )

        # Skip further processing for irrelevant emails
        match: MatchResult | None = None
        if classification.category.value != "IRRELEVANT":
            match = match_email_to_application(
                conn,
                to_address=em.to_address,
            )
            if match:
                result.matched += 1
                logger.info(
                    "Matched email to application: %s at %s",
                    match.opportunity.title,
                    match.opportunity.company,
                )
            else:
                logger.info("No application match for to=%s", em.to_address)

        pe = ProcessedEmail(email=em, classification=classification, match=match)

        if not dry_run:
            _persist_email(conn, pe)

            # Create work item for actionable emails
            if (
                classification.requires_action
                and classification.category in ACTIONABLE_CATEGORIES
                and match is not None
            ):
                wi_id = _create_review_work_item(conn, pe)
                pe.work_item_id = wi_id
                result.work_items_created += 1

        result.processed.append(pe)

    # 4. Send Telegram briefing (only non-IRRELEVANT emails)
    relevant = [
        p for p in result.processed if p.classification.category.value != "IRRELEVANT"
    ]
    logger.info(
        "Preparing Telegram briefing: %d relevant emails (%d total processed)",
        len(relevant),
        len(result.processed),
    )

    if not dry_run:
        tg_cfg = telegram_config or _safe_get_telegram_config()
        if tg_cfg:
            briefing = _format_briefing(relevant)
            result.notification_sent = await send_telegram_message(tg_cfg, briefing)
            if result.notification_sent:
                logger.info("Telegram briefing sent successfully")
            else:
                logger.error(
                    "Telegram briefing FAILED to send — check bot token and chat ID"
                )
        else:
            logger.error(
                "Telegram not configured — briefing NOT sent. "
                "Set EMPLAIYED_TELEGRAM_BOT_TOKEN and EMPLAIYED_TELEGRAM_CHAT_ID in .env"
            )

    _log_run_summary(result, run_start)
    return result


def _safe_get_telegram_config() -> TelegramConfig | None:
    """Load Telegram config, returning None instead of raising on missing creds."""
    try:
        return get_telegram_config()
    except RuntimeError as exc:
        logger.error("Telegram config error: %s", exc)
        return None


def _log_run_summary(result: MonitorResult, run_start: float) -> None:
    """Log a structured end-of-run summary."""
    elapsed = time.monotonic() - run_start
    logger.info(
        "=== Inbox check finished in %.1fs | "
        "fetched=%d already_seen=%d classified=%d matched=%d "
        "work_items=%d telegram_sent=%s errors=%d ===",
        elapsed,
        result.total_fetched,
        result.already_processed,
        result.classified,
        result.matched,
        result.work_items_created,
        result.notification_sent,
        len(result.errors),
    )
    if result.errors:
        for err in result.errors:
            logger.warning("  Run error: %s", err)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _persist_email(conn: sqlite3.Connection, pe: ProcessedEmail) -> None:
    """Record a processed email in the database."""
    now = datetime.now().isoformat()

    save_processed_email(
        conn,
        id=str(uuid4()),
        message_id=pe.email.message_id or str(uuid4()),
        from_address=pe.email.from_address,
        subject=pe.email.subject,
        received_at=pe.email.date.isoformat() if pe.email.date else None,
        category=pe.classification.category.value,
        matched_app_id=pe.match.application.id if pe.match else None,
        summary=pe.classification.summary,
        processed_at=now,
    )

    # Record an EMAIL_RECEIVED interaction if matched
    if pe.match:
        interaction = Interaction(
            application_id=pe.match.application.id,
            type=InteractionType.EMAIL_RECEIVED,
            direction="inbound",
            channel="email",
            content=pe.classification.summary,
            metadata={
                "from": pe.email.from_address,
                "subject": pe.email.subject,
                "category": pe.classification.category.value,
                "message_id": pe.email.message_id,
            },
            created_at=datetime.now(),
        )
        save_interaction(conn, interaction)


def _create_review_work_item(conn: sqlite3.Connection, pe: ProcessedEmail) -> str:
    """Create a REVIEW_RESPONSE work item for an actionable email.

    Unlike outreach/follow-up work items, inbox work items do NOT
    trigger a state transition — the user decides what to do.
    We use save_work_item directly instead of create_work_item
    to skip the state machine.
    """
    assert pe.match is not None

    app = pe.match.application
    opp = pe.match.opportunity
    cat_label = pe.classification.category.value.replace("_", " ").title()

    item = WorkItem(
        application_id=app.id,
        work_type=WorkType.REVIEW_RESPONSE,
        title=f"{cat_label} from {opp.company}",
        instructions=(
            f"**{cat_label}** received from {opp.company} — {opp.title}\n\n"
            f"**From:** {pe.email.from_name} <{pe.email.from_address}>\n"
            f"**Subject:** {pe.email.subject}\n\n"
            f"**Summary:** {pe.classification.summary}\n\n"
            + (
                f"**Suggested next step:** {pe.classification.suggested_next_step}\n\n"
                if pe.classification.suggested_next_step
                else ""
            )
            + f"Review the email and take appropriate action."
        ),
        draft_content=None,
        target_status=ApplicationStatus.RESPONSE_RECEIVED.value,
        previous_status=app.status.value,
        created_at=datetime.now(),
    )
    save_work_item(conn, item)
    logger.debug(
        "Created REVIEW_RESPONSE work item %s for %s", item.id[:8], opp.company
    )
    return item.id
