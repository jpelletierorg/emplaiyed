"""Tests for the application lifecycle state machine."""

from __future__ import annotations

from datetime import datetime

import pytest

from emplaiyed.core.database import (
    save_application,
    save_opportunity,
    get_application,
)
from emplaiyed.core.models import Application, ApplicationStatus
from emplaiyed.tracker.state_machine import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    can_transition,
    transition,
)


def _make_app(status: ApplicationStatus) -> Application:
    return Application(
        id="app-1",
        opportunity_id="opp-1",
        status=status,
        created_at=datetime(2025, 1, 15, 11, 0, 0),
        updated_at=datetime(2025, 1, 15, 11, 0, 0),
    )


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS structure
# ---------------------------------------------------------------------------


class TestValidTransitionsStructure:
    def test_all_statuses_have_entries(self):
        """Every ApplicationStatus should have an entry in VALID_TRANSITIONS."""
        for status in ApplicationStatus:
            assert status in VALID_TRANSITIONS, f"{status.value} missing from VALID_TRANSITIONS"

    def test_terminal_states_have_no_transitions(self):
        assert VALID_TRANSITIONS[ApplicationStatus.ACCEPTED] == set()
        assert VALID_TRANSITIONS[ApplicationStatus.REJECTED] == set()
        assert VALID_TRANSITIONS[ApplicationStatus.PASSED] == set()

    def test_ghosted_can_receive_response(self):
        """GHOSTED is not fully terminal — they might reply later."""
        assert ApplicationStatus.RESPONSE_RECEIVED in VALID_TRANSITIONS[ApplicationStatus.GHOSTED]


# ---------------------------------------------------------------------------
# can_transition
# ---------------------------------------------------------------------------


class TestCanTransition:
    # --- Happy path transitions (all valid ones) ---

    def test_discovered_to_scored(self):
        assert can_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.SCORED)

    def test_scored_to_outreach_pending(self):
        assert can_transition(ApplicationStatus.SCORED, ApplicationStatus.OUTREACH_PENDING)

    def test_scored_to_outreach_sent(self):
        """Backward compat: auto-send still works."""
        assert can_transition(ApplicationStatus.SCORED, ApplicationStatus.OUTREACH_SENT)

    def test_outreach_pending_to_outreach_sent(self):
        assert can_transition(ApplicationStatus.OUTREACH_PENDING, ApplicationStatus.OUTREACH_SENT)

    def test_outreach_pending_to_scored(self):
        """Skip reverts to SCORED."""
        assert can_transition(ApplicationStatus.OUTREACH_PENDING, ApplicationStatus.SCORED)

    def test_outreach_sent_to_follow_up_pending(self):
        assert can_transition(ApplicationStatus.OUTREACH_SENT, ApplicationStatus.FOLLOW_UP_PENDING)

    def test_outreach_sent_to_follow_up_1(self):
        """Backward compat: auto-send still works."""
        assert can_transition(ApplicationStatus.OUTREACH_SENT, ApplicationStatus.FOLLOW_UP_1)

    def test_outreach_sent_to_response_received(self):
        assert can_transition(ApplicationStatus.OUTREACH_SENT, ApplicationStatus.RESPONSE_RECEIVED)

    def test_outreach_sent_to_ghosted(self):
        assert can_transition(ApplicationStatus.OUTREACH_SENT, ApplicationStatus.GHOSTED)

    def test_follow_up_pending_to_follow_up_1(self):
        assert can_transition(ApplicationStatus.FOLLOW_UP_PENDING, ApplicationStatus.FOLLOW_UP_1)

    def test_follow_up_pending_to_follow_up_2(self):
        assert can_transition(ApplicationStatus.FOLLOW_UP_PENDING, ApplicationStatus.FOLLOW_UP_2)

    def test_follow_up_pending_to_outreach_sent(self):
        """Skip reverts to previous state."""
        assert can_transition(ApplicationStatus.FOLLOW_UP_PENDING, ApplicationStatus.OUTREACH_SENT)

    def test_follow_up_1_to_follow_up_pending(self):
        assert can_transition(ApplicationStatus.FOLLOW_UP_1, ApplicationStatus.FOLLOW_UP_PENDING)

    def test_follow_up_1_to_follow_up_2(self):
        """Backward compat: auto-send still works."""
        assert can_transition(ApplicationStatus.FOLLOW_UP_1, ApplicationStatus.FOLLOW_UP_2)

    def test_follow_up_1_to_response_received(self):
        assert can_transition(ApplicationStatus.FOLLOW_UP_1, ApplicationStatus.RESPONSE_RECEIVED)

    def test_follow_up_1_to_ghosted(self):
        assert can_transition(ApplicationStatus.FOLLOW_UP_1, ApplicationStatus.GHOSTED)

    def test_follow_up_2_to_response_received(self):
        assert can_transition(ApplicationStatus.FOLLOW_UP_2, ApplicationStatus.RESPONSE_RECEIVED)

    def test_follow_up_2_to_ghosted(self):
        assert can_transition(ApplicationStatus.FOLLOW_UP_2, ApplicationStatus.GHOSTED)

    def test_response_received_to_interview_scheduled(self):
        assert can_transition(ApplicationStatus.RESPONSE_RECEIVED, ApplicationStatus.INTERVIEW_SCHEDULED)

    def test_response_received_to_rejected(self):
        assert can_transition(ApplicationStatus.RESPONSE_RECEIVED, ApplicationStatus.REJECTED)

    def test_interview_scheduled_to_interview_completed(self):
        assert can_transition(ApplicationStatus.INTERVIEW_SCHEDULED, ApplicationStatus.INTERVIEW_COMPLETED)

    def test_interview_scheduled_to_rejected(self):
        assert can_transition(ApplicationStatus.INTERVIEW_SCHEDULED, ApplicationStatus.REJECTED)

    def test_interview_completed_to_interview_scheduled(self):
        """Another round of interviews."""
        assert can_transition(ApplicationStatus.INTERVIEW_COMPLETED, ApplicationStatus.INTERVIEW_SCHEDULED)

    def test_interview_completed_to_offer_received(self):
        assert can_transition(ApplicationStatus.INTERVIEW_COMPLETED, ApplicationStatus.OFFER_RECEIVED)

    def test_interview_completed_to_rejected(self):
        assert can_transition(ApplicationStatus.INTERVIEW_COMPLETED, ApplicationStatus.REJECTED)

    def test_offer_received_to_negotiation_pending(self):
        assert can_transition(ApplicationStatus.OFFER_RECEIVED, ApplicationStatus.NEGOTIATION_PENDING)

    def test_offer_received_to_acceptance_pending(self):
        assert can_transition(ApplicationStatus.OFFER_RECEIVED, ApplicationStatus.ACCEPTANCE_PENDING)

    def test_offer_received_to_negotiating(self):
        """Backward compat."""
        assert can_transition(ApplicationStatus.OFFER_RECEIVED, ApplicationStatus.NEGOTIATING)

    def test_offer_received_to_accepted(self):
        """Backward compat."""
        assert can_transition(ApplicationStatus.OFFER_RECEIVED, ApplicationStatus.ACCEPTED)

    def test_offer_received_to_rejected(self):
        assert can_transition(ApplicationStatus.OFFER_RECEIVED, ApplicationStatus.REJECTED)

    def test_negotiation_pending_to_negotiating(self):
        assert can_transition(ApplicationStatus.NEGOTIATION_PENDING, ApplicationStatus.NEGOTIATING)

    def test_negotiation_pending_to_offer_received(self):
        """Skip reverts."""
        assert can_transition(ApplicationStatus.NEGOTIATION_PENDING, ApplicationStatus.OFFER_RECEIVED)

    def test_negotiating_to_offer_received(self):
        """Counter-offer."""
        assert can_transition(ApplicationStatus.NEGOTIATING, ApplicationStatus.OFFER_RECEIVED)

    def test_negotiating_to_acceptance_pending(self):
        assert can_transition(ApplicationStatus.NEGOTIATING, ApplicationStatus.ACCEPTANCE_PENDING)

    def test_negotiating_to_accepted(self):
        """Backward compat."""
        assert can_transition(ApplicationStatus.NEGOTIATING, ApplicationStatus.ACCEPTED)

    def test_negotiating_to_rejected(self):
        assert can_transition(ApplicationStatus.NEGOTIATING, ApplicationStatus.REJECTED)

    def test_acceptance_pending_to_accepted(self):
        assert can_transition(ApplicationStatus.ACCEPTANCE_PENDING, ApplicationStatus.ACCEPTED)

    def test_acceptance_pending_to_offer_received(self):
        """Skip reverts."""
        assert can_transition(ApplicationStatus.ACCEPTANCE_PENDING, ApplicationStatus.OFFER_RECEIVED)

    def test_acceptance_pending_to_negotiating(self):
        """Skip reverts from negotiating path."""
        assert can_transition(ApplicationStatus.ACCEPTANCE_PENDING, ApplicationStatus.NEGOTIATING)

    def test_scored_to_passed(self):
        assert can_transition(ApplicationStatus.SCORED, ApplicationStatus.PASSED)

    def test_outreach_pending_to_passed(self):
        assert can_transition(ApplicationStatus.OUTREACH_PENDING, ApplicationStatus.PASSED)

    def test_ghosted_to_response_received(self):
        assert can_transition(ApplicationStatus.GHOSTED, ApplicationStatus.RESPONSE_RECEIVED)

    # --- Invalid transitions ---

    def test_cannot_skip_scored(self):
        assert not can_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.OUTREACH_SENT)

    def test_cannot_go_backwards(self):
        assert not can_transition(ApplicationStatus.SCORED, ApplicationStatus.DISCOVERED)

    def test_cannot_leave_accepted(self):
        for target in ApplicationStatus:
            if target != ApplicationStatus.ACCEPTED:
                assert not can_transition(ApplicationStatus.ACCEPTED, target), (
                    f"ACCEPTED should not transition to {target.value}"
                )

    def test_cannot_leave_rejected(self):
        for target in ApplicationStatus:
            if target != ApplicationStatus.REJECTED:
                assert not can_transition(ApplicationStatus.REJECTED, target), (
                    f"REJECTED should not transition to {target.value}"
                )

    def test_cannot_leave_passed(self):
        for target in ApplicationStatus:
            if target != ApplicationStatus.PASSED:
                assert not can_transition(ApplicationStatus.PASSED, target), (
                    f"PASSED should not transition to {target.value}"
                )

    def test_discovered_cannot_pass(self):
        assert not can_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.PASSED)

    def test_cannot_self_transition(self):
        """No status should transition to itself."""
        for status in ApplicationStatus:
            assert not can_transition(status, status), (
                f"{status.value} should not transition to itself"
            )

    def test_discovered_cannot_go_to_interview(self):
        assert not can_transition(ApplicationStatus.DISCOVERED, ApplicationStatus.INTERVIEW_SCHEDULED)

    def test_ghosted_cannot_go_to_accepted(self):
        assert not can_transition(ApplicationStatus.GHOSTED, ApplicationStatus.ACCEPTED)


# ---------------------------------------------------------------------------
# transition (database integration)
# ---------------------------------------------------------------------------


class TestTransition:
    def test_valid_transition_updates_db(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
    ):
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.DISCOVERED)
        save_application(db, app)

        result = transition(db, "app-1", ApplicationStatus.SCORED)
        assert result.status == ApplicationStatus.SCORED

        # Verify the database was updated
        loaded = get_application(db, "app-1")
        assert loaded.status == ApplicationStatus.SCORED
        assert loaded.updated_at > app.updated_at

    def test_invalid_transition_raises(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
    ):
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.DISCOVERED)
        save_application(db, app)

        with pytest.raises(InvalidTransitionError) as exc_info:
            transition(db, "app-1", ApplicationStatus.INTERVIEW_SCHEDULED)

        assert "DISCOVERED" in str(exc_info.value)
        assert "INTERVIEW_SCHEDULED" in str(exc_info.value)

        # Verify the database was NOT changed
        loaded = get_application(db, "app-1")
        assert loaded.status == ApplicationStatus.DISCOVERED

    def test_terminal_state_raises(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
    ):
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.ACCEPTED)
        save_application(db, app)

        with pytest.raises(InvalidTransitionError) as exc_info:
            transition(db, "app-1", ApplicationStatus.REJECTED)

        assert "terminal" in str(exc_info.value).lower()

    def test_nonexistent_application_raises_value_error(
        self,
        db: sqlite3.Connection,
    ):
        with pytest.raises(ValueError, match="Application not found"):
            transition(db, "nonexistent", ApplicationStatus.SCORED)

    def test_ghosted_to_response_received(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
    ):
        """Special case: a ghosted application can get a response."""
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.GHOSTED)
        save_application(db, app)

        result = transition(db, "app-1", ApplicationStatus.RESPONSE_RECEIVED)
        assert result.status == ApplicationStatus.RESPONSE_RECEIVED

    def test_multi_step_happy_path(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
    ):
        """Walk through the entire happy path with PENDING states."""
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.DISCOVERED)
        save_application(db, app)

        steps = [
            ApplicationStatus.SCORED,
            ApplicationStatus.OUTREACH_PENDING,
            ApplicationStatus.OUTREACH_SENT,
            ApplicationStatus.FOLLOW_UP_PENDING,
            ApplicationStatus.FOLLOW_UP_1,
            ApplicationStatus.RESPONSE_RECEIVED,
            ApplicationStatus.INTERVIEW_SCHEDULED,
            ApplicationStatus.INTERVIEW_COMPLETED,
            ApplicationStatus.OFFER_RECEIVED,
            ApplicationStatus.NEGOTIATION_PENDING,
            ApplicationStatus.NEGOTIATING,
            ApplicationStatus.ACCEPTANCE_PENDING,
            ApplicationStatus.ACCEPTED,
        ]

        for target in steps:
            result = transition(db, "app-1", target)
            assert result.status == target

        # After ACCEPTED, nothing should be valid
        with pytest.raises(InvalidTransitionError):
            transition(db, "app-1", ApplicationStatus.REJECTED)

    def test_interview_loop(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
    ):
        """Multiple rounds of interviews."""
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.RESPONSE_RECEIVED)
        save_application(db, app)

        # Round 1
        transition(db, "app-1", ApplicationStatus.INTERVIEW_SCHEDULED)
        transition(db, "app-1", ApplicationStatus.INTERVIEW_COMPLETED)
        # Round 2
        transition(db, "app-1", ApplicationStatus.INTERVIEW_SCHEDULED)
        transition(db, "app-1", ApplicationStatus.INTERVIEW_COMPLETED)
        # Round 3 -> offer
        transition(db, "app-1", ApplicationStatus.OFFER_RECEIVED)

        loaded = get_application(db, "app-1")
        assert loaded.status == ApplicationStatus.OFFER_RECEIVED

    def test_scored_to_passed(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
    ):
        """SCORED applications can be marked as PASSED (not interested)."""
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.SCORED)
        save_application(db, app)

        result = transition(db, "app-1", ApplicationStatus.PASSED)
        assert result.status == ApplicationStatus.PASSED

        # Terminal: can't transition out
        with pytest.raises(InvalidTransitionError):
            transition(db, "app-1", ApplicationStatus.OUTREACH_PENDING)

    def test_negotiation_loop(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
    ):
        """Counter-offer cycle: OFFER_RECEIVED -> NEGOTIATING -> OFFER_RECEIVED -> ACCEPTED."""
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.OFFER_RECEIVED)
        save_application(db, app)

        transition(db, "app-1", ApplicationStatus.NEGOTIATING)
        transition(db, "app-1", ApplicationStatus.OFFER_RECEIVED)
        transition(db, "app-1", ApplicationStatus.ACCEPTED)

        loaded = get_application(db, "app-1")
        assert loaded.status == ApplicationStatus.ACCEPTED


# ---------------------------------------------------------------------------
# InvalidTransitionError
# ---------------------------------------------------------------------------


class TestInvalidTransitionError:
    def test_error_message_includes_states(self):
        err = InvalidTransitionError(
            ApplicationStatus.DISCOVERED,
            ApplicationStatus.INTERVIEW_SCHEDULED,
        )
        assert "DISCOVERED" in str(err)
        assert "INTERVIEW_SCHEDULED" in str(err)

    def test_error_message_includes_application_id(self):
        err = InvalidTransitionError(
            ApplicationStatus.DISCOVERED,
            ApplicationStatus.INTERVIEW_SCHEDULED,
            application_id="app-123",
        )
        assert "app-123" in str(err)

    def test_error_message_for_terminal_state(self):
        err = InvalidTransitionError(
            ApplicationStatus.ACCEPTED,
            ApplicationStatus.REJECTED,
        )
        assert "terminal" in str(err).lower()

    def test_error_attributes(self):
        err = InvalidTransitionError(
            ApplicationStatus.DISCOVERED,
            ApplicationStatus.SCORED,
            application_id="app-x",
        )
        assert err.current == ApplicationStatus.DISCOVERED
        assert err.target == ApplicationStatus.SCORED
        assert err.application_id == "app-x"
