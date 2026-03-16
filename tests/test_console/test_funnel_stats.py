"""Tests for funnel statistics computation — pure functions, no DB needed."""

from __future__ import annotations

from datetime import datetime, timedelta

from emplaiyed.console.funnel_stats import FunnelSnapshot, StageStats, compute_funnel
from emplaiyed.console.stages import STAGE_GROUPS, STAGE_TAB_ORDER
from emplaiyed.core.models import Application, ApplicationStatus, StatusTransition


def _app(id: str, status: ApplicationStatus, score: int = 50) -> Application:
    now = datetime(2025, 3, 1)
    return Application(
        id=id,
        opportunity_id=f"opp-{id}",
        status=status,
        score=score,
        created_at=now,
        updated_at=now,
    )


def _transition(
    app_id: str,
    from_s: str,
    to_s: str,
    at: datetime | None = None,
) -> StatusTransition:
    return StatusTransition(
        application_id=app_id,
        from_status=from_s,
        to_status=to_s,
        transitioned_at=at or datetime(2025, 3, 1),
    )


class TestStageGroups:
    def test_all_pipeline_statuses_covered(self):
        """Every non-Queue status should appear in exactly one stage group."""
        all_statuses = set()
        for statuses in STAGE_GROUPS.values():
            for s in statuses:
                assert s not in all_statuses, f"{s} appears in multiple groups"
                all_statuses.add(s)

    def test_tab_order_matches_groups(self):
        """All stage group names should appear in STAGE_TAB_ORDER."""
        for name in STAGE_GROUPS:
            assert name in STAGE_TAB_ORDER


class TestComputeFunnelEmpty:
    def test_empty_inputs(self):
        result = compute_funnel([], [])
        assert isinstance(result, FunnelSnapshot)
        assert result.total == 0
        assert result.active == 0
        assert result.closed == 0
        assert len(result.stages) == 4

    def test_all_stages_have_zero_count(self):
        result = compute_funnel([], [])
        for stage in result.stages:
            assert stage.count == 0


class TestComputeFunnelCounts:
    def test_single_stage(self):
        apps = [
            _app("a1", ApplicationStatus.OUTREACH_SENT),
            _app("a2", ApplicationStatus.FOLLOW_UP_1),
        ]
        result = compute_funnel(apps, [])
        applied = next(s for s in result.stages if s.name == "Applied")
        assert applied.count == 2

    def test_all_in_one_stage(self):
        apps = [_app(f"a{i}", ApplicationStatus.OUTREACH_SENT) for i in range(5)]
        result = compute_funnel(apps, [])
        applied = next(s for s in result.stages if s.name == "Applied")
        assert applied.count == 5
        active = next(s for s in result.stages if s.name == "Active")
        assert active.count == 0

    def test_mixed_stages(self):
        apps = [
            _app("a1", ApplicationStatus.OUTREACH_SENT),
            _app("a2", ApplicationStatus.INTERVIEW_SCHEDULED),
            _app("a3", ApplicationStatus.OFFER_RECEIVED),
            _app("a4", ApplicationStatus.REJECTED),
        ]
        result = compute_funnel(apps, [])
        assert result.total == 4
        assert result.active == 3
        assert result.closed == 1
        applied = next(s for s in result.stages if s.name == "Applied")
        assert applied.count == 1
        active = next(s for s in result.stages if s.name == "Active")
        assert active.count == 1
        offers = next(s for s in result.stages if s.name == "Offers")
        assert offers.count == 1
        closed = next(s for s in result.stages if s.name == "Closed")
        assert closed.count == 1

    def test_pre_pipeline_apps_not_counted(self):
        """DISCOVERED, SCORED, etc. don't belong to any stage group."""
        apps = [
            _app("a1", ApplicationStatus.DISCOVERED),
            _app("a2", ApplicationStatus.SCORED),
            _app("a3", ApplicationStatus.OUTREACH_PENDING),
        ]
        result = compute_funnel(apps, [])
        assert result.total == 3
        for stage in result.stages:
            assert stage.count == 0


class TestConversionRates:
    def test_conversion_from_applied_to_active(self):
        apps = [
            _app("a1", ApplicationStatus.INTERVIEW_SCHEDULED),
        ]
        transitions = [
            _transition("a1", "SCORED", "OUTREACH_SENT"),
            _transition("a1", "OUTREACH_SENT", "RESPONSE_RECEIVED"),
            _transition("a1", "RESPONSE_RECEIVED", "INTERVIEW_SCHEDULED"),
        ]
        result = compute_funnel(apps, transitions)
        active = next(s for s in result.stages if s.name == "Active")
        # 1 reached Active out of 1 that reached Applied = 100%
        assert active.conversion_pct == 100.0

    def test_conversion_with_dropoff(self):
        apps = [
            _app("a1", ApplicationStatus.INTERVIEW_SCHEDULED),
            _app("a2", ApplicationStatus.GHOSTED),
        ]
        transitions = [
            _transition("a1", "SCORED", "OUTREACH_SENT"),
            _transition("a1", "OUTREACH_SENT", "RESPONSE_RECEIVED"),
            _transition("a1", "RESPONSE_RECEIVED", "INTERVIEW_SCHEDULED"),
            _transition("a2", "SCORED", "OUTREACH_SENT"),
            _transition("a2", "OUTREACH_SENT", "GHOSTED"),
        ]
        result = compute_funnel(apps, transitions)
        applied = next(s for s in result.stages if s.name == "Applied")
        assert applied.conversion_pct is None  # first stage, no previous
        active = next(s for s in result.stages if s.name == "Active")
        # 1 reached Active out of 2 that reached Applied = 50%
        assert active.conversion_pct == 50.0

    def test_applied_has_no_conversion_pct(self):
        """Applied is the first stage — no conversion percentage."""
        result = compute_funnel([], [])
        applied = next(s for s in result.stages if s.name == "Applied")
        assert applied.conversion_pct is None


class TestClosedBreakdown:
    def test_empty_when_no_closed_apps(self):
        apps = [_app("a1", ApplicationStatus.OUTREACH_SENT)]
        result = compute_funnel(apps, [])
        assert result.closed_breakdown == {}

    def test_breakdown_by_reason(self):
        apps = [
            _app("a1", ApplicationStatus.REJECTED),
            _app("a2", ApplicationStatus.REJECTED),
            _app("a3", ApplicationStatus.GHOSTED),
            _app("a4", ApplicationStatus.PASSED),
        ]
        result = compute_funnel(apps, [])
        assert result.closed_breakdown == {
            "REJECTED": 2,
            "GHOSTED": 1,
            "PASSED": 1,
        }

    def test_only_nonzero_reasons_included(self):
        apps = [_app("a1", ApplicationStatus.GHOSTED)]
        result = compute_funnel(apps, [])
        assert result.closed_breakdown == {"GHOSTED": 1}
        assert "REJECTED" not in result.closed_breakdown
        assert "ACCEPTED" not in result.closed_breakdown

    def test_accepted_appears_in_breakdown(self):
        apps = [_app("a1", ApplicationStatus.ACCEPTED)]
        result = compute_funnel(apps, [])
        assert result.closed_breakdown == {"ACCEPTED": 1}


class TestBelowThresholdInFunnel:
    """BELOW_THRESHOLD apps are counted in total but not in any stage group."""

    def test_bt_apps_not_in_any_stage(self):
        apps = [
            _app("a1", ApplicationStatus.BELOW_THRESHOLD, score=10),
            _app("a2", ApplicationStatus.BELOW_THRESHOLD, score=20),
        ]
        result = compute_funnel(apps, [])
        assert result.total == 2
        for stage in result.stages:
            assert stage.count == 0, f"BT apps should not appear in {stage.name}"

    def test_bt_apps_counted_in_total_alongside_others(self):
        apps = [
            _app("a1", ApplicationStatus.BELOW_THRESHOLD, score=10),
            _app("a2", ApplicationStatus.OUTREACH_SENT, score=50),
            _app("a3", ApplicationStatus.REJECTED, score=30),
        ]
        result = compute_funnel(apps, [])
        assert result.total == 3
        assert result.active == 2  # BT + OUTREACH_SENT (non-closed)
        assert result.closed == 1
        applied = next(s for s in result.stages if s.name == "Applied")
        assert applied.count == 1  # only OUTREACH_SENT

    def test_bt_not_in_closed_breakdown(self):
        apps = [_app("a1", ApplicationStatus.BELOW_THRESHOLD, score=10)]
        result = compute_funnel(apps, [])
        assert "BELOW_THRESHOLD" not in result.closed_breakdown


class TestAvgTimeInStage:
    def test_avg_time_computed(self):
        t0 = datetime(2025, 3, 1, 10, 0)
        t1 = datetime(2025, 3, 1, 12, 0)  # 2 hours later
        t2 = datetime(2025, 3, 3, 12, 0)  # 2 days later
        apps = [_app("a1", ApplicationStatus.INTERVIEW_SCHEDULED)]
        transitions = [
            _transition("a1", "SCORED", "OUTREACH_SENT", t0),
            _transition("a1", "OUTREACH_SENT", "RESPONSE_RECEIVED", t1),
            _transition("a1", "RESPONSE_RECEIVED", "INTERVIEW_SCHEDULED", t2),
        ]
        result = compute_funnel(apps, transitions)
        applied = next(s for s in result.stages if s.name == "Applied")
        # OUTREACH_SENT entered at t0, left at t1 (2 hours)
        assert applied.avg_time_in_stage is not None
        assert applied.avg_time_in_stage == timedelta(hours=2)

    def test_no_transitions_means_no_avg_time(self):
        apps = [_app("a1", ApplicationStatus.OUTREACH_SENT)]
        result = compute_funnel(apps, [])
        applied = next(s for s in result.stages if s.name == "Applied")
        assert applied.avg_time_in_stage is None
