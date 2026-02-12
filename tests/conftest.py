"""Shared test fixtures — DRY helpers available to all test modules."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from emplaiyed.core.database import init_db
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Interaction,
    InteractionType,
    Opportunity,
)


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    """Return an initialised in-memory test database connection."""
    return init_db(tmp_path / "test.db")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return the path to a test database (initialised)."""
    p = tmp_path / "test.db"
    init_db(p).close()
    return p


@pytest.fixture
def sample_opportunity() -> Opportunity:
    return Opportunity(
        id="opp-1",
        source="indeed",
        source_url="https://indeed.com/job/123",
        company="Acme Corp",
        title="Backend Developer",
        description="Build REST APIs",
        location="Montreal",
        salary_min=80000,
        salary_max=110000,
        scraped_at=datetime(2025, 1, 15, 10, 30, 0),
    )


@pytest.fixture
def sample_application() -> Application:
    return Application(
        id="app-00001111-2222-3333-4444-555566667777",
        opportunity_id="opp-1",
        status=ApplicationStatus.DISCOVERED,
        created_at=datetime(2025, 1, 15, 11, 0, 0),
        updated_at=datetime(2025, 1, 15, 11, 0, 0),
    )


@pytest.fixture
def sample_interaction() -> Interaction:
    return Interaction(
        id="int-1",
        application_id="app-00001111-2222-3333-4444-555566667777",
        type=InteractionType.EMAIL_SENT,
        direction="outbound",
        channel="email",
        content="Dear hiring manager, I am writing to express my interest...",
        metadata={"subject": "Application for Backend Developer", "to": "hr@acme.com"},
        created_at=datetime(2025, 1, 16, 9, 0, 0),
    )
