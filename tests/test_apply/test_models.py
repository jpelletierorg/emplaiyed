"""Tests for ApplyRun model and database CRUD."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from emplaiyed.core.database import (
    get_active_apply_run,
    get_apply_run,
    init_db,
    list_apply_runs,
    save_apply_run,
    save_application,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    ApplyRun,
    ApplyRunStatus,
    Opportunity,
    PortalKind,
)


@pytest.fixture
def db(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def opp_and_app(db):
    """Create and save an opportunity and application, return (opp, app)."""
    opp = Opportunity(
        id="opp-1",
        source="test",
        source_url="https://example.com/job/1",
        company="TestCo",
        title="Engineer",
        description="Do stuff",
        scraped_at=datetime.now(),
    )
    save_opportunity(db, opp)

    app = Application(
        id="app-1",
        opportunity_id="opp-1",
        status=ApplicationStatus.SCORED,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    save_application(db, app)
    return opp, app


class TestApplyRunModel:
    def test_defaults(self):
        now = datetime.now()
        run = ApplyRun(application_id="app-1", started_at=now, updated_at=now)
        assert run.status == ApplyRunStatus.QUEUED
        assert run.portal_kind == PortalKind.UNKNOWN
        assert run.id  # auto-generated
        assert run.current_url is None
        assert run.error_message is None
        assert run.completed_at is None

    def test_all_fields(self):
        now = datetime.now()
        run = ApplyRun(
            id="run-1",
            application_id="app-1",
            status=ApplyRunStatus.FILLING,
            portal_kind=PortalKind.GREENHOUSE,
            current_url="https://boards.greenhouse.io/co/123",
            last_step="Filling form",
            error_message=None,
            artifact_dir="/tmp/assets/app-1",
            started_at=now,
            updated_at=now,
        )
        assert run.status == ApplyRunStatus.FILLING
        assert run.portal_kind == PortalKind.GREENHOUSE


class TestApplyRunCRUD:
    def test_save_and_get(self, db, opp_and_app):
        now = datetime.now()
        run = ApplyRun(
            id="run-1",
            application_id="app-1",
            started_at=now,
            updated_at=now,
        )
        save_apply_run(db, run)

        loaded = get_apply_run(db, "run-1")
        assert loaded is not None
        assert loaded.id == "run-1"
        assert loaded.application_id == "app-1"
        assert loaded.status == ApplyRunStatus.QUEUED

    def test_get_nonexistent(self, db):
        assert get_apply_run(db, "nope") is None

    def test_update(self, db, opp_and_app):
        now = datetime.now()
        run = ApplyRun(
            id="run-1",
            application_id="app-1",
            started_at=now,
            updated_at=now,
        )
        save_apply_run(db, run)

        updated = run.model_copy(
            update={
                "status": ApplyRunStatus.NAVIGATING,
                "last_step": "Opening URL",
                "updated_at": datetime.now(),
            }
        )
        save_apply_run(db, updated)

        loaded = get_apply_run(db, "run-1")
        assert loaded is not None
        assert loaded.status == ApplyRunStatus.NAVIGATING
        assert loaded.last_step == "Opening URL"

    def test_list_apply_runs(self, db, opp_and_app):
        now = datetime.now()
        for i in range(3):
            run = ApplyRun(
                id=f"run-{i}",
                application_id="app-1",
                started_at=now,
                updated_at=now,
            )
            save_apply_run(db, run)

        runs = list_apply_runs(db, application_id="app-1")
        assert len(runs) == 3

    def test_list_all(self, db, opp_and_app):
        now = datetime.now()
        save_apply_run(
            db,
            ApplyRun(
                id="run-1", application_id="app-1", started_at=now, updated_at=now
            ),
        )
        runs = list_apply_runs(db)
        assert len(runs) == 1

    def test_get_active_apply_run(self, db, opp_and_app):
        now = datetime.now()

        # No active run
        assert get_active_apply_run(db, "app-1") is None

        # Add a queued run
        run = ApplyRun(
            id="run-1",
            application_id="app-1",
            started_at=now,
            updated_at=now,
        )
        save_apply_run(db, run)
        active = get_active_apply_run(db, "app-1")
        assert active is not None
        assert active.id == "run-1"

        # Complete it — should no longer be active
        completed = run.model_copy(
            update={
                "status": ApplyRunStatus.SUCCEEDED,
                "updated_at": datetime.now(),
            }
        )
        save_apply_run(db, completed)
        assert get_active_apply_run(db, "app-1") is None

    def test_get_active_ignores_failed_blocked(self, db, opp_and_app):
        now = datetime.now()
        for status in (
            ApplyRunStatus.FAILED,
            ApplyRunStatus.BLOCKED,
            ApplyRunStatus.CANCELLED,
        ):
            run = ApplyRun(
                application_id="app-1",
                status=status,
                started_at=now,
                updated_at=now,
            )
            save_apply_run(db, run)

        assert get_active_apply_run(db, "app-1") is None

    def test_portal_kind_persisted(self, db, opp_and_app):
        now = datetime.now()
        run = ApplyRun(
            id="run-pk",
            application_id="app-1",
            portal_kind=PortalKind.LEVER,
            started_at=now,
            updated_at=now,
        )
        save_apply_run(db, run)

        loaded = get_apply_run(db, "run-pk")
        assert loaded is not None
        assert loaded.portal_kind == PortalKind.LEVER
