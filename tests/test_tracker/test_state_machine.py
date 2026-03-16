"""Tests for the application lifecycle state machine."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from emplaiyed.core.database import (
    list_status_transitions,
    save_application,
    save_opportunity,
    get_application,
)
from emplaiyed.core.models import Application, ApplicationStatus, Opportunity
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


# Build parametrize lists from the VALID_TRANSITIONS dict itself.
_VALID_CASES = [
    (src, tgt) for src, targets in VALID_TRANSITIONS.items() for tgt in targets
]

_TERMINAL = {
    ApplicationStatus.ACCEPTED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.PASSED,
}


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS structure
# ---------------------------------------------------------------------------


class TestValidTransitionsStructure:
    def test_all_statuses_have_entries(self):
        for status in ApplicationStatus:
            assert status in VALID_TRANSITIONS, f"{status.value} missing"

    def test_terminal_states_have_no_transitions(self):
        for s in _TERMINAL:
            assert VALID_TRANSITIONS[s] == set(), f"{s.value} should be terminal"

    def test_ghosted_can_receive_response(self):
        assert (
            ApplicationStatus.RESPONSE_RECEIVED
            in VALID_TRANSITIONS[ApplicationStatus.GHOSTED]
        )


# ---------------------------------------------------------------------------
# can_transition
# ---------------------------------------------------------------------------


class TestCanTransition:
    @pytest.mark.parametrize(
        "src,tgt", _VALID_CASES, ids=[f"{s.value}->{t.value}" for s, t in _VALID_CASES]
    )
    def test_valid_transition(self, src, tgt):
        assert can_transition(src, tgt)

    def test_cannot_self_transition(self):
        for status in ApplicationStatus:
            assert not can_transition(status, status), f"{status.value} -> itself"

    @pytest.mark.parametrize(
        "terminal", list(_TERMINAL), ids=[s.value for s in _TERMINAL]
    )
    def test_cannot_leave_terminal(self, terminal):
        for target in ApplicationStatus:
            if target != terminal:
                assert not can_transition(terminal, target), (
                    f"{terminal.value} -> {target.value}"
                )

    def test_applied_statuses_can_be_rejected(self):
        """OUTREACH_SENT, FOLLOW_UP_1, FOLLOW_UP_2 can all transition to REJECTED."""
        for status in (
            ApplicationStatus.OUTREACH_SENT,
            ApplicationStatus.FOLLOW_UP_1,
            ApplicationStatus.FOLLOW_UP_2,
        ):
            assert can_transition(status, ApplicationStatus.REJECTED), (
                f"{status.value} -> REJECTED should be valid"
            )

    def test_cannot_skip_stages(self):
        assert not can_transition(
            ApplicationStatus.DISCOVERED, ApplicationStatus.OUTREACH_SENT
        )
        assert not can_transition(
            ApplicationStatus.DISCOVERED, ApplicationStatus.INTERVIEW_SCHEDULED
        )
        assert not can_transition(ApplicationStatus.GHOSTED, ApplicationStatus.ACCEPTED)

    def test_cannot_go_backwards(self):
        assert not can_transition(
            ApplicationStatus.SCORED, ApplicationStatus.DISCOVERED
        )


# ---------------------------------------------------------------------------
# transition (database integration)
# ---------------------------------------------------------------------------


class TestTransition:
    def test_valid_transition_updates_db(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.DISCOVERED)
        save_application(db, app)

        result = transition(db, "app-1", ApplicationStatus.SCORED)
        assert result.status == ApplicationStatus.SCORED
        loaded = get_application(db, "app-1")
        assert loaded.status == ApplicationStatus.SCORED
        assert loaded.updated_at > app.updated_at

    def test_invalid_transition_raises(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        app = _make_app(ApplicationStatus.DISCOVERED)
        save_application(db, app)

        with pytest.raises(InvalidTransitionError) as exc_info:
            transition(db, "app-1", ApplicationStatus.INTERVIEW_SCHEDULED)
        assert "DISCOVERED" in str(exc_info.value)

        loaded = get_application(db, "app-1")
        assert loaded.status == ApplicationStatus.DISCOVERED

    def test_terminal_state_raises(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.ACCEPTED))

        with pytest.raises(InvalidTransitionError) as exc_info:
            transition(db, "app-1", ApplicationStatus.REJECTED)
        assert "terminal" in str(exc_info.value).lower()

    def test_nonexistent_application_raises(self, db: sqlite3.Connection):
        with pytest.raises(ValueError, match="Application not found"):
            transition(db, "nonexistent", ApplicationStatus.SCORED)

    def test_multi_step_happy_path(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.DISCOVERED))

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

        with pytest.raises(InvalidTransitionError):
            transition(db, "app-1", ApplicationStatus.REJECTED)

    def test_interview_loop(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.RESPONSE_RECEIVED))

        transition(db, "app-1", ApplicationStatus.INTERVIEW_SCHEDULED)
        transition(db, "app-1", ApplicationStatus.INTERVIEW_COMPLETED)
        transition(db, "app-1", ApplicationStatus.INTERVIEW_SCHEDULED)
        transition(db, "app-1", ApplicationStatus.INTERVIEW_COMPLETED)
        transition(db, "app-1", ApplicationStatus.OFFER_RECEIVED)

        assert get_application(db, "app-1").status == ApplicationStatus.OFFER_RECEIVED

    def test_negotiation_loop(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.OFFER_RECEIVED))

        transition(db, "app-1", ApplicationStatus.NEGOTIATING)
        transition(db, "app-1", ApplicationStatus.OFFER_RECEIVED)
        transition(db, "app-1", ApplicationStatus.ACCEPTED)

        assert get_application(db, "app-1").status == ApplicationStatus.ACCEPTED

    def test_transition_records_history(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.DISCOVERED))

        transition(db, "app-1", ApplicationStatus.SCORED)
        transition(db, "app-1", ApplicationStatus.OUTREACH_PENDING)

        history = list_status_transitions(db, "app-1")
        assert len(history) == 2
        assert history[0].from_status == "DISCOVERED"
        assert history[1].to_status == "OUTREACH_PENDING"

    def test_invalid_transition_does_not_record_history(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.DISCOVERED))

        with pytest.raises(InvalidTransitionError):
            transition(db, "app-1", ApplicationStatus.INTERVIEW_SCHEDULED)

        assert len(list_status_transitions(db, "app-1")) == 0


# ---------------------------------------------------------------------------
# InvalidTransitionError
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BELOW_THRESHOLD specific transitions
# ---------------------------------------------------------------------------


class TestBelowThresholdTransitions:
    """Explicit tests for BELOW_THRESHOLD state transitions."""

    def test_discovered_to_below_threshold(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.DISCOVERED))
        result = transition(db, "app-1", ApplicationStatus.BELOW_THRESHOLD)
        assert result.status == ApplicationStatus.BELOW_THRESHOLD

    def test_scored_to_below_threshold(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.SCORED))
        result = transition(db, "app-1", ApplicationStatus.BELOW_THRESHOLD)
        assert result.status == ApplicationStatus.BELOW_THRESHOLD

    def test_below_threshold_to_scored(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.BELOW_THRESHOLD))
        result = transition(db, "app-1", ApplicationStatus.SCORED)
        assert result.status == ApplicationStatus.SCORED

    def test_below_threshold_to_passed(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.BELOW_THRESHOLD))
        result = transition(db, "app-1", ApplicationStatus.PASSED)
        assert result.status == ApplicationStatus.PASSED

    def test_below_threshold_cannot_go_to_outreach(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        """BT apps cannot skip to OUTREACH_PENDING — must promote to SCORED first."""
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.BELOW_THRESHOLD))
        with pytest.raises(InvalidTransitionError):
            transition(db, "app-1", ApplicationStatus.OUTREACH_PENDING)

    def test_below_threshold_records_history(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.DISCOVERED))
        transition(db, "app-1", ApplicationStatus.BELOW_THRESHOLD)
        history = list_status_transitions(db, "app-1")
        assert len(history) == 1
        assert history[0].from_status == "DISCOVERED"
        assert history[0].to_status == "BELOW_THRESHOLD"

    def test_promote_then_outreach_happy_path(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        """BT → SCORED → OUTREACH_PENDING works as a two-step promotion."""
        save_opportunity(db, sample_opportunity)
        save_application(db, _make_app(ApplicationStatus.BELOW_THRESHOLD))
        transition(db, "app-1", ApplicationStatus.SCORED)
        transition(db, "app-1", ApplicationStatus.OUTREACH_PENDING)
        assert get_application(db, "app-1").status == ApplicationStatus.OUTREACH_PENDING


# ---------------------------------------------------------------------------
# InvalidTransitionError
# ---------------------------------------------------------------------------


class TestInvalidTransitionError:
    def test_error_attributes_and_message(self):
        err = InvalidTransitionError(
            ApplicationStatus.DISCOVERED,
            ApplicationStatus.SCORED,
            application_id="app-x",
        )
        assert err.current == ApplicationStatus.DISCOVERED
        assert err.target == ApplicationStatus.SCORED
        assert err.application_id == "app-x"
        assert "app-x" in str(err)
        assert "DISCOVERED" in str(err)

    def test_terminal_state_message(self):
        err = InvalidTransitionError(
            ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED
        )
        assert "terminal" in str(err).lower()
