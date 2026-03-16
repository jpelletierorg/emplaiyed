"""Tests for emplaiyed.inbox.monitor — the orchestrator."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, TextPart

from emplaiyed.core.database import (
    init_db,
    is_email_processed,
    list_processed_emails,
    list_work_items,
    save_application,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Opportunity,
    WorkStatus,
)
from emplaiyed.inbox.config import ImapConfig, TelegramConfig
from emplaiyed.inbox.fetcher import FetchedEmail
from emplaiyed.inbox.monitor import MonitorResult, _format_briefing, run_inbox_check


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def imap_config():
    return ImapConfig(host="mail.test.com", port=993, user="u", password="p")


@pytest.fixture
def tg_config():
    return TelegramConfig(bot_token="tok", chat_id="cid")


def _make_email(
    msg_id: str = "<test@msg>",
    from_addr: str = "hr@acme.com",
    to_addr: str = "moi+tEsT01@jpelletier.org",
    subject: str = "Interview invite",
    body: str = "We'd like to schedule an interview.",
) -> FetchedEmail:
    return FetchedEmail(
        message_id=msg_id,
        from_address=from_addr,
        from_name="Acme HR",
        to_address=to_addr,
        subject=subject,
        date=datetime.now(),
        body_text=body,
    )


def _classifier_model(category: str = "INTERVIEW_INVITE", action: bool = True):
    """Return a FunctionModel that always produces the given classification."""
    payload = {
        "category": category,
        "requires_action": action,
        "urgency": "high" if action else "low",
        "summary": f"Test: {category}",
        "suggested_next_step": "Reply" if action else None,
    }

    async def _handler(messages, info):
        return ModelResponse(parts=[TextPart(content=json.dumps(payload))])

    return FunctionModel(_handler)


def _seed_db(db, short_id: str = "tEsT01"):
    """Insert an opportunity + application into the DB."""
    opp = Opportunity(
        id="opp-1",
        short_id=short_id,
        source="test",
        company="Acme Corp",
        title="Developer",
        description="Test",
        scraped_at=datetime.now(),
    )
    save_opportunity(db, opp)
    app = Application(
        id="app-1",
        opportunity_id="opp-1",
        status=ApplicationStatus.OUTREACH_SENT,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    save_application(db, app)
    return opp, app


# ---------------------------------------------------------------------------
# Tests for _format_briefing
# ---------------------------------------------------------------------------


class TestFormatBriefing:
    def test_empty_list(self):
        msg = _format_briefing([])
        assert "No new job-related emails" in msg

    def test_non_empty(self):
        from emplaiyed.inbox.classifier import EmailCategory, EmailClassification
        from emplaiyed.inbox.monitor import ProcessedEmail

        classification = EmailClassification(
            category=EmailCategory.INTERVIEW_INVITE,
            requires_action=True,
            urgency="high",
            summary="Interview at Acme",
            suggested_next_step="Reply to schedule",
        )
        pe = ProcessedEmail(
            email=_make_email(),
            classification=classification,
            match=None,
        )
        msg = _format_briefing([pe])
        assert "Action Required" in msg
        assert "Interview at Acme" in msg


# ---------------------------------------------------------------------------
# Tests for run_inbox_check
# ---------------------------------------------------------------------------


class TestRunInboxCheck:
    async def test_no_emails(self, db, imap_config, tg_config):
        """When IMAP returns no emails, result is empty."""
        with patch("emplaiyed.inbox.monitor.fetch_recent_emails", return_value=[]):
            with patch(
                "emplaiyed.inbox.monitor.send_telegram_message",
                new_callable=AsyncMock,
                return_value=True,
            ):
                result = await run_inbox_check(
                    db,
                    imap_config=imap_config,
                    telegram_config=tg_config,
                )
        assert result.total_fetched == 0
        assert result.classified == 0

    async def test_classify_and_match(self, db, imap_config, tg_config):
        """Email gets classified, matched via plus-tag, and recorded."""
        _seed_db(db, short_id="tEsT01")
        emails = [_make_email(to_addr="moi+tEsT01@jpelletier.org")]

        model = _classifier_model("INTERVIEW_INVITE", action=True)

        with patch("emplaiyed.inbox.monitor.fetch_recent_emails", return_value=emails):
            with patch(
                "emplaiyed.inbox.monitor.send_telegram_message",
                new_callable=AsyncMock,
                return_value=True,
            ):
                result = await run_inbox_check(
                    db,
                    imap_config=imap_config,
                    telegram_config=tg_config,
                    _model_override=model,
                )

        assert result.total_fetched == 1
        assert result.classified == 1
        assert result.matched == 1
        assert result.work_items_created == 1
        assert result.notification_sent is True

        # Check DB was updated
        assert is_email_processed(db, "<test@msg>")
        processed = list_processed_emails(db)
        assert len(processed) == 1
        assert processed[0]["category"] == "INTERVIEW_INVITE"

        # Check work item was created
        items = list_work_items(db)
        pending = [wi for wi in items if wi.status == WorkStatus.PENDING]
        assert len(pending) == 1
        assert "REVIEW_RESPONSE" == pending[0].work_type.value

    async def test_deduplication(self, db, imap_config, tg_config):
        """Already-processed emails are skipped."""
        _seed_db(db)
        emails = [_make_email(msg_id="<dup@msg>")]
        model = _classifier_model("IRRELEVANT", action=False)

        # First run — processes the email
        with patch("emplaiyed.inbox.monitor.fetch_recent_emails", return_value=emails):
            with patch(
                "emplaiyed.inbox.monitor.send_telegram_message",
                new_callable=AsyncMock,
                return_value=True,
            ):
                r1 = await run_inbox_check(
                    db,
                    imap_config=imap_config,
                    telegram_config=tg_config,
                    _model_override=model,
                )
        assert r1.classified == 1
        assert r1.already_processed == 0

        # Second run — same email is deduplicated
        with patch("emplaiyed.inbox.monitor.fetch_recent_emails", return_value=emails):
            with patch(
                "emplaiyed.inbox.monitor.send_telegram_message",
                new_callable=AsyncMock,
                return_value=True,
            ):
                r2 = await run_inbox_check(
                    db,
                    imap_config=imap_config,
                    telegram_config=tg_config,
                    _model_override=model,
                )
        assert r2.already_processed == 1
        assert r2.classified == 0

    async def test_dry_run(self, db, imap_config, tg_config):
        """Dry run classifies but does not persist or notify."""
        _seed_db(db)
        emails = [_make_email()]
        model = _classifier_model("INTERVIEW_INVITE", action=True)

        with patch("emplaiyed.inbox.monitor.fetch_recent_emails", return_value=emails):
            result = await run_inbox_check(
                db,
                imap_config=imap_config,
                telegram_config=tg_config,
                dry_run=True,
                _model_override=model,
            )

        assert result.classified == 1
        assert result.work_items_created == 0
        assert result.notification_sent is False
        # Nothing persisted
        assert not is_email_processed(db, "<test@msg>")

    async def test_irrelevant_no_work_item(self, db, imap_config, tg_config):
        """Irrelevant emails don't create work items."""
        _seed_db(db)
        emails = [_make_email(from_addr="spam@newsletter.com", subject="Deals!")]
        model = _classifier_model("IRRELEVANT", action=False)

        with patch("emplaiyed.inbox.monitor.fetch_recent_emails", return_value=emails):
            with patch(
                "emplaiyed.inbox.monitor.send_telegram_message",
                new_callable=AsyncMock,
                return_value=True,
            ):
                result = await run_inbox_check(
                    db,
                    imap_config=imap_config,
                    telegram_config=tg_config,
                    _model_override=model,
                )

        assert result.classified == 1
        assert result.matched == 0
        assert result.work_items_created == 0
