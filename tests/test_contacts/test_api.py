"""Tests for the contacts API endpoints."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from emplaiyed.api.app import create_app
from emplaiyed.core.database import (
    _MIGRATIONS,
    _POST_MIGRATIONS,
    _SCHEMA,
    save_application,
    save_contact,
    save_opportunity,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Contact,
    Opportunity,
)


def _init_test_db(path):
    """Init a test database with check_same_thread=False for TestClient."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(_SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    for stmt in _POST_MIGRATIONS:
        conn.execute(stmt)
    conn.commit()
    return conn


@pytest.fixture()
def app_client(tmp_path):
    """Create a test client with an isolated database."""
    import emplaiyed.api.deps as deps

    db_path = tmp_path / "test.db"
    conn = _init_test_db(db_path)

    # Seed data
    opp = Opportunity(
        id="opp-test-1",
        source="talent",
        company="API Test Corp",
        title="Engineer",
        description="Test job posting with recruiter@apitest.com",
        scraped_at=datetime.now(),
        raw_data={"job_id": "api-1"},
    )
    save_opportunity(conn, opp)

    app_record = Application(
        id="app-test-1",
        opportunity_id="opp-test-1",
        status=ApplicationStatus.FOLLOW_UP_PENDING,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    save_application(conn, app_record)

    # Override deps
    original_db_conn = deps._db_conn

    def _override_get_db():
        yield conn

    deps._db_conn = conn

    app = create_app()
    app.dependency_overrides[deps.get_db] = _override_get_db

    client = TestClient(app)
    yield client

    # Cleanup
    app.dependency_overrides.clear()
    deps._db_conn = original_db_conn
    conn.close()


class TestListContacts:
    def test_empty_contacts(self, app_client):
        resp = app_client.get("/api/contacts/opp-test-1")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_with_contacts(self, app_client):
        # Save a contact directly
        import emplaiyed.api.deps as deps

        conn = deps._db_conn
        contact = Contact(
            id="contact-1",
            opportunity_id="opp-test-1",
            name="Test Contact",
            email="test@contact.com",
            source="manual",
            confidence=1.0,
        )
        save_contact(conn, contact)

        resp = app_client.get("/api/contacts/opp-test-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Contact"
        assert data[0]["email"] == "test@contact.com"


class TestExtractContacts:
    def test_opportunity_not_found(self, app_client):
        resp = app_client.post("/api/contacts/nonexistent-opp/extract")
        assert resp.status_code == 404
