from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from emplaiyed.core.database import (
    active_opportunity_keys,
    delete_application,
    delete_event,
    get_default_db_path,
    get_application,
    get_event,
    get_offer,
    get_opportunity,
    get_work_item,
    init_db,
    list_applications,
    list_applications_by_statuses,
    list_events,
    list_interactions,
    list_offers,
    list_opportunities,
    list_pending_work_items,
    list_status_transitions,
    list_upcoming_events,
    list_work_items,
    rebuild_search_index,
    reclassify_threshold_apps,
    save_application,
    save_event,
    save_interaction,
    save_offer,
    save_opportunity,
    save_status_transition,
    save_work_item,
    search_opportunities,
)
from emplaiyed.core.models import (
    Application,
    ApplicationStatus,
    Interaction,
    InteractionType,
    Offer,
    OfferStatus,
    Opportunity,
    ScheduledEvent,
    StatusTransition,
    WorkItem,
    WorkStatus,
    WorkType,
)


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
        posted_date=date(2025, 1, 10),
        scraped_at=datetime(2025, 1, 15, 10, 30, 0),
        raw_data={"original_id": "abc123", "tags": ["python", "remote"]},
    )


@pytest.fixture
def sample_application() -> Application:
    return Application(
        id="app-1",
        opportunity_id="opp-1",
        status=ApplicationStatus.DISCOVERED,
        created_at=datetime(2025, 1, 15, 11, 0, 0),
        updated_at=datetime(2025, 1, 15, 11, 0, 0),
    )


@pytest.fixture
def sample_interaction() -> Interaction:
    return Interaction(
        id="int-1",
        application_id="app-1",
        type=InteractionType.EMAIL_SENT,
        direction="outbound",
        channel="email",
        content="Dear hiring manager, I am writing to express my interest...",
        metadata={"subject": "Application for Backend Developer", "to": "hr@acme.com"},
        created_at=datetime(2025, 1, 16, 9, 0, 0),
    )


@pytest.fixture
def sample_offer() -> Offer:
    return Offer(
        id="off-1",
        application_id="app-1",
        salary=95000,
        currency="CAD",
        benefits="Health, dental, RRSP matching",
        conditions="3-month probation",
        start_date=date(2025, 3, 1),
        deadline=date(2025, 2, 20),
        status=OfferStatus.PENDING,
        created_at=datetime(2025, 2, 10, 14, 0, 0),
    )


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInitDb:
    def test_creates_database_file(self, tmp_path: Path):
        db_path = tmp_path / "new.db"
        conn = init_db(db_path)
        assert db_path.exists()
        conn.close()

    def test_creates_parent_directories(self, tmp_path: Path):
        db_path = tmp_path / "nested" / "deep" / "test.db"
        conn = init_db(db_path)
        assert db_path.exists()
        conn.close()

    def test_creates_all_tables(self, db: sqlite3.Connection):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = sorted(row["name"] for row in cur.fetchall())
        assert "applications" in tables
        assert "interactions" in tables
        assert "offers" in tables
        assert "opportunities" in tables
        assert "scheduled_events" in tables
        assert "work_items" in tables

    def test_idempotent_and_migrations(self, tmp_path: Path):
        """Calling init_db twice should not error; migrations add scoring columns."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        # Verify scoring columns exist after migration
        save_opportunity(
            conn,
            Opportunity(
                id="opp-m",
                source="test",
                company="Co",
                title="Dev",
                description="D",
                scraped_at=datetime(2025, 1, 1, 0, 0, 0),
            ),
        )
        app = Application(
            id="app-m",
            opportunity_id="opp-m",
            status=ApplicationStatus.SCORED,
            score=75,
            justification="Good fit",
            day_to_day="Write code",
            why_it_fits="Skills align",
            created_at=datetime(2025, 1, 1),
            updated_at=datetime(2025, 1, 1),
        )
        save_application(conn, app)
        assert get_application(conn, "app-m").score == 75
        conn.close()
        # Second init should not fail
        conn2 = init_db(db_path)
        conn2.close()


# ---------------------------------------------------------------------------
# Opportunity CRUD
# ---------------------------------------------------------------------------


class TestOpportunityCRUD:
    def test_save_and_get(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        loaded = get_opportunity(db, "opp-1")
        assert loaded is not None
        assert loaded.id == "opp-1"
        assert loaded.company == "Acme Corp"
        assert loaded.source_url == "https://indeed.com/job/123"
        assert loaded.salary_min == 80000
        assert loaded.salary_max == 110000
        assert loaded.posted_date == date(2025, 1, 10)
        assert loaded.scraped_at == datetime(2025, 1, 15, 10, 30, 0)

    def test_raw_data_round_trip(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        loaded = get_opportunity(db, "opp-1")
        assert loaded.raw_data == {
            "original_id": "abc123",
            "tags": ["python", "remote"],
        }

    def test_get_nonexistent_returns_none(self, db: sqlite3.Connection):
        assert get_opportunity(db, "does-not-exist") is None

    def test_list_all(self, db: sqlite3.Connection):
        for i in range(3):
            opp = Opportunity(
                id=f"opp-{i}",
                source="indeed",
                company=f"Co-{i}",
                title="Dev",
                description="Stuff",
                scraped_at=datetime(2025, 1, 15, 10, i, 0),
            )
            save_opportunity(db, opp)
        results = list_opportunities(db)
        assert len(results) == 3

    def test_list_with_filter(self, db: sqlite3.Connection):
        for source in ["indeed", "linkedin", "indeed"]:
            opp = Opportunity(
                source=source,
                company="Co",
                title="Dev",
                description="D",
                scraped_at=datetime.now(),
            )
            save_opportunity(db, opp)
        indeed = list_opportunities(db, source="indeed")
        assert len(indeed) == 2
        linkedin = list_opportunities(db, source="linkedin")
        assert len(linkedin) == 1

    def test_upsert_replaces(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        updated = sample_opportunity.model_copy(
            update={"title": "Senior Backend Developer"}
        )
        save_opportunity(db, updated)
        loaded = get_opportunity(db, "opp-1")
        assert loaded.title == "Senior Backend Developer"
        assert len(list_opportunities(db)) == 1

    def test_null_optional_fields(self, db: sqlite3.Connection):
        opp = Opportunity(
            id="opp-minimal",
            source="manual",
            company="Startup",
            title="Engineer",
            description="Build products",
            scraped_at=datetime(2025, 1, 20, 8, 0, 0),
        )
        save_opportunity(db, opp)
        loaded = get_opportunity(db, "opp-minimal")
        assert loaded.source_url is None
        assert loaded.location is None
        assert loaded.salary_min is None
        assert loaded.salary_max is None
        assert loaded.posted_date is None
        assert loaded.raw_data is None


# ---------------------------------------------------------------------------
# Application CRUD
# ---------------------------------------------------------------------------


class TestApplicationCRUD:
    def test_save_and_get(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        loaded = get_application(db, "app-1")
        assert loaded is not None
        assert loaded.opportunity_id == "opp-1"
        assert loaded.status == ApplicationStatus.DISCOVERED
        # Scoring fields default to None
        assert loaded.score is None
        assert loaded.justification is None

    def test_get_nonexistent_returns_none(self, db: sqlite3.Connection):
        assert get_application(db, "nope") is None

    def test_list_all(self, db: sqlite3.Connection, sample_opportunity: Opportunity):
        save_opportunity(db, sample_opportunity)
        for i in range(3):
            app = Application(
                id=f"app-{i}",
                opportunity_id="opp-1",
                status=ApplicationStatus.DISCOVERED,
                created_at=datetime(2025, 1, 15, 11, i, 0),
                updated_at=datetime(2025, 1, 15, 11, i, 0),
            )
            save_application(db, app)
        assert len(list_applications(db)) == 3

    def test_list_filter_by_status(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        for i, status in enumerate(
            [
                ApplicationStatus.DISCOVERED,
                ApplicationStatus.SCORED,
                ApplicationStatus.DISCOVERED,
            ]
        ):
            app = Application(
                id=f"app-{i}",
                opportunity_id="opp-1",
                status=status,
                created_at=datetime(2025, 1, 15, 11, i, 0),
                updated_at=datetime(2025, 1, 15, 11, i, 0),
            )
            save_application(db, app)
        discovered = list_applications(db, status=ApplicationStatus.DISCOVERED)
        assert len(discovered) == 2
        scored = list_applications(db, status=ApplicationStatus.SCORED)
        assert len(scored) == 1

    def test_save_and_get_with_scoring_fields(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
        save_opportunity(db, sample_opportunity)
        app = Application(
            id="app-scored",
            opportunity_id="opp-1",
            status=ApplicationStatus.SCORED,
            score=85,
            justification="Strong Python match",
            day_to_day="Build REST APIs and deploy to AWS.",
            why_it_fits="Deep Python and cloud experience aligns perfectly.",
            created_at=datetime(2025, 1, 15, 11, 0, 0),
            updated_at=datetime(2025, 1, 15, 11, 0, 0),
        )
        save_application(db, app)
        loaded = get_application(db, "app-scored")
        assert loaded is not None
        assert loaded.score == 85
        assert loaded.justification == "Strong Python match"
        assert loaded.day_to_day == "Build REST APIs and deploy to AWS."
        assert (
            loaded.why_it_fits == "Deep Python and cloud experience aligns perfectly."
        )

    def test_upsert_updates_status(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        updated = sample_application.model_copy(
            update={
                "status": ApplicationStatus.OUTREACH_SENT,
                "updated_at": datetime(2025, 1, 16, 10, 0, 0),
            }
        )
        save_application(db, updated)
        loaded = get_application(db, "app-1")
        assert loaded.status == ApplicationStatus.OUTREACH_SENT


class TestDeleteApplication:
    """Tests for cascading application deletion."""

    def _seed(self, db: sqlite3.Connection) -> tuple:
        """Seed an opportunity + application + related data. Returns (opp, app)."""
        opp = Opportunity(
            id="opp-del",
            source="test",
            company="DeleteCo",
            title="To Be Deleted",
            description="desc",
            scraped_at=datetime(2025, 1, 1),
        )
        save_opportunity(db, opp)
        app = Application(
            id="app-del",
            opportunity_id="opp-del",
            status=ApplicationStatus.SCORED,
            created_at=datetime(2025, 1, 1),
            updated_at=datetime(2025, 1, 1),
        )
        save_application(db, app)
        save_interaction(
            db,
            Interaction(
                id="int-del",
                application_id="app-del",
                type=InteractionType.NOTE,
                direction="internal",
                channel="internal",
                content="test note",
                created_at=datetime(2025, 1, 2),
            ),
        )
        save_status_transition(
            db,
            StatusTransition(
                id="st-del",
                application_id="app-del",
                from_status=ApplicationStatus.DISCOVERED,
                to_status=ApplicationStatus.SCORED,
                transitioned_at=datetime(2025, 1, 2),
            ),
        )
        return opp, app

    def test_deletes_application_and_related_data(self, db: sqlite3.Connection):
        self._seed(db)
        delete_application(db, "app-del")
        assert get_application(db, "app-del") is None
        assert list_interactions(db, application_id="app-del") == []
        assert list_status_transitions(db, "app-del") == []

    def test_deletes_orphaned_opportunity(self, db: sqlite3.Connection):
        self._seed(db)
        delete_application(db, "app-del")
        assert get_opportunity(db, "opp-del") is None

    def test_keeps_opportunity_if_other_apps_reference_it(self, db: sqlite3.Connection):
        self._seed(db)
        # Add a second application referencing the same opportunity
        app2 = Application(
            id="app-keep",
            opportunity_id="opp-del",
            status=ApplicationStatus.DISCOVERED,
            created_at=datetime(2025, 1, 1),
            updated_at=datetime(2025, 1, 1),
        )
        save_application(db, app2)
        delete_application(db, "app-del")
        assert get_application(db, "app-del") is None
        assert get_opportunity(db, "opp-del") is not None

    def test_delete_nonexistent_is_noop(self, db: sqlite3.Connection):
        """Deleting a non-existent application should not error."""
        delete_application(db, "does-not-exist")


# ---------------------------------------------------------------------------
# Interaction CRUD
# ---------------------------------------------------------------------------


class TestInteractionCRUD:
    def test_save_and_list(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
        sample_interaction: Interaction,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        save_interaction(db, sample_interaction)
        interactions = list_interactions(db, "app-1")
        assert len(interactions) == 1
        assert interactions[0].id == "int-1"
        assert interactions[0].type == InteractionType.EMAIL_SENT
        assert interactions[0].direction == "outbound"
        assert interactions[0].channel == "email"
        assert "hiring manager" in interactions[0].content

    def test_metadata_round_trip(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
        sample_interaction: Interaction,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        save_interaction(db, sample_interaction)
        loaded = list_interactions(db, "app-1")[0]
        assert loaded.metadata == {
            "subject": "Application for Backend Developer",
            "to": "hr@acme.com",
        }

    def test_multiple_interactions_ordered(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        for i in range(3):
            interaction = Interaction(
                id=f"int-{i}",
                application_id="app-1",
                type=InteractionType.NOTE,
                direction="outbound",
                channel="internal",
                content=f"Note {i}",
                created_at=datetime(2025, 1, 16, 9, i, 0),
            )
            save_interaction(db, interaction)
        interactions = list_interactions(db, "app-1")
        assert len(interactions) == 3
        # Should be ordered by created_at
        assert interactions[0].content == "Note 0"
        assert interactions[2].content == "Note 2"

    def test_null_optional_fields(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        interaction = Interaction(
            id="int-minimal",
            application_id="app-1",
            type=InteractionType.PHONE_CALL,
            direction="inbound",
            channel="phone",
            created_at=datetime(2025, 1, 17, 10, 0, 0),
        )
        save_interaction(db, interaction)
        loaded = list_interactions(db, "app-1")[0]
        assert loaded.content is None
        assert loaded.metadata is None


# ---------------------------------------------------------------------------
# Offer CRUD
# ---------------------------------------------------------------------------


class TestOfferCRUD:
    def test_save_and_get(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
        sample_offer: Offer,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        save_offer(db, sample_offer)
        loaded = get_offer(db, "off-1")
        assert loaded is not None
        assert loaded.salary == 95000
        assert loaded.currency == "CAD"
        assert loaded.benefits == "Health, dental, RRSP matching"
        assert loaded.start_date == date(2025, 3, 1)
        assert loaded.deadline == date(2025, 2, 20)
        assert loaded.status == OfferStatus.PENDING

    def test_get_nonexistent_returns_none(self, db: sqlite3.Connection):
        assert get_offer(db, "nope") is None

    def test_list_all(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        for i in range(2):
            offer = Offer(
                id=f"off-{i}",
                application_id="app-1",
                salary=90000 + i * 5000,
                status=OfferStatus.PENDING,
                created_at=datetime(2025, 2, 10, 14, i, 0),
            )
            save_offer(db, offer)
        assert len(list_offers(db)) == 2

    def test_list_filter_by_status(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        for i, status in enumerate(
            [OfferStatus.PENDING, OfferStatus.ACCEPTED, OfferStatus.PENDING]
        ):
            offer = Offer(
                id=f"off-{i}",
                application_id="app-1",
                salary=90000,
                status=status,
                created_at=datetime(2025, 2, 10, 14, i, 0),
            )
            save_offer(db, offer)
        pending = list_offers(db, status=OfferStatus.PENDING)
        assert len(pending) == 2
        accepted = list_offers(db, status=OfferStatus.ACCEPTED)
        assert len(accepted) == 1

    def test_upsert_updates_status(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
        sample_offer: Offer,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        save_offer(db, sample_offer)
        updated = sample_offer.model_copy(update={"status": OfferStatus.ACCEPTED})
        save_offer(db, updated)
        loaded = get_offer(db, "off-1")
        assert loaded.status == OfferStatus.ACCEPTED
        assert len(list_offers(db)) == 1

    def test_null_optional_fields(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        offer = Offer(
            id="off-minimal",
            application_id="app-1",
            status=OfferStatus.PENDING,
            created_at=datetime(2025, 2, 11, 8, 0, 0),
        )
        save_offer(db, offer)
        loaded = get_offer(db, "off-minimal")
        assert loaded.salary is None
        assert loaded.benefits is None
        assert loaded.conditions is None
        assert loaded.start_date is None
        assert loaded.deadline is None
        assert loaded.currency == "CAD"


# ---------------------------------------------------------------------------
# Scheduled Event CRUD
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_event() -> ScheduledEvent:
    return ScheduledEvent(
        id="evt-1",
        application_id="app-1",
        event_type="phone_screen",
        scheduled_date=datetime(2025, 1, 14, 14, 0, 0),
        notes="With Sarah Chen, Talent Acquisition",
        created_at=datetime(2025, 1, 12, 10, 0, 0),
    )


class TestScheduledEventCRUD:
    def test_save_and_get(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
        sample_event: ScheduledEvent,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        save_event(db, sample_event)
        loaded = get_event(db, "evt-1")
        assert loaded is not None
        assert loaded.id == "evt-1"
        assert loaded.application_id == "app-1"
        assert loaded.event_type == "phone_screen"
        assert loaded.scheduled_date == datetime(2025, 1, 14, 14, 0, 0)
        assert loaded.notes == "With Sarah Chen, Talent Acquisition"
        assert loaded.created_at == datetime(2025, 1, 12, 10, 0, 0)

    def test_get_nonexistent_returns_none(self, db: sqlite3.Connection):
        assert get_event(db, "does-not-exist") is None

    def test_list_all(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        for i in range(3):
            event = ScheduledEvent(
                id=f"evt-{i}",
                application_id="app-1",
                event_type="phone_screen",
                scheduled_date=datetime(2025, 1, 14 + i, 14, 0, 0),
                created_at=datetime(2025, 1, 12, 10, 0, 0),
            )
            save_event(db, event)
        results = list_events(db)
        assert len(results) == 3

    def test_list_filter_by_application_id(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
    ):
        save_opportunity(db, sample_opportunity)
        # Create two different applications
        for app_id in ["app-a", "app-b"]:
            app = Application(
                id=app_id,
                opportunity_id="opp-1",
                status=ApplicationStatus.INTERVIEW_SCHEDULED,
                created_at=datetime(2025, 1, 15, 11, 0, 0),
                updated_at=datetime(2025, 1, 15, 11, 0, 0),
            )
            save_application(db, app)

        save_event(
            db,
            ScheduledEvent(
                id="evt-a1",
                application_id="app-a",
                event_type="phone_screen",
                scheduled_date=datetime(2025, 1, 14, 14, 0, 0),
                created_at=datetime(2025, 1, 12, 10, 0, 0),
            ),
        )
        save_event(
            db,
            ScheduledEvent(
                id="evt-b1",
                application_id="app-b",
                event_type="technical_interview",
                scheduled_date=datetime(2025, 1, 15, 10, 0, 0),
                created_at=datetime(2025, 1, 12, 10, 0, 0),
            ),
        )
        save_event(
            db,
            ScheduledEvent(
                id="evt-a2",
                application_id="app-a",
                event_type="onsite",
                scheduled_date=datetime(2025, 1, 20, 9, 0, 0),
                created_at=datetime(2025, 1, 12, 10, 0, 0),
            ),
        )

        app_a_events = list_events(db, application_id="app-a")
        assert len(app_a_events) == 2
        app_b_events = list_events(db, application_id="app-b")
        assert len(app_b_events) == 1

    def test_list_filter_by_date_range(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)

        # Create events across different dates
        for day in [10, 14, 18, 22]:
            save_event(
                db,
                ScheduledEvent(
                    id=f"evt-jan{day}",
                    application_id="app-1",
                    event_type="phone_screen",
                    scheduled_date=datetime(2025, 1, day, 14, 0, 0),
                    created_at=datetime(2025, 1, 8, 10, 0, 0),
                ),
            )

        # Filter date_from only
        from_jan15 = list_events(db, date_from=datetime(2025, 1, 15, 0, 0, 0))
        assert len(from_jan15) == 2  # Jan 18 and Jan 22

        # Filter date_to only
        to_jan15 = list_events(db, date_to=datetime(2025, 1, 15, 0, 0, 0))
        assert len(to_jan15) == 2  # Jan 10 and Jan 14

        # Filter both
        range_events = list_events(
            db,
            date_from=datetime(2025, 1, 12, 0, 0, 0),
            date_to=datetime(2025, 1, 20, 0, 0, 0),
        )
        assert len(range_events) == 2  # Jan 14 and Jan 18

    def test_list_events_ordered_by_scheduled_date(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)

        # Insert in reverse order
        for day in [20, 10, 15]:
            save_event(
                db,
                ScheduledEvent(
                    id=f"evt-jan{day}",
                    application_id="app-1",
                    event_type="phone_screen",
                    scheduled_date=datetime(2025, 1, day, 14, 0, 0),
                    created_at=datetime(2025, 1, 8, 10, 0, 0),
                ),
            )

        events = list_events(db)
        assert len(events) == 3
        assert (
            events[0].scheduled_date
            < events[1].scheduled_date
            < events[2].scheduled_date
        )

    def test_list_upcoming_filters_past_and_sorts(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)

        save_event(
            db,
            ScheduledEvent(
                id="evt-past",
                application_id="app-1",
                event_type="phone_screen",
                scheduled_date=datetime(2020, 1, 1, 10, 0, 0),
                created_at=datetime(2019, 12, 28, 10, 0, 0),
            ),
        )
        for year in [2099, 2098, 2097]:
            save_event(
                db,
                ScheduledEvent(
                    id=f"evt-{year}",
                    application_id="app-1",
                    event_type="phone_screen",
                    scheduled_date=datetime(year, 6, 15, 10, 0, 0),
                    created_at=datetime(year, 6, 1, 10, 0, 0),
                ),
            )

        upcoming = list_upcoming_events(db)
        assert len(upcoming) == 3  # past excluded
        assert (
            upcoming[0].scheduled_date
            < upcoming[1].scheduled_date
            < upcoming[2].scheduled_date
        )

    def test_delete_event(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
        sample_event: ScheduledEvent,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        save_event(db, sample_event)

        assert get_event(db, "evt-1") is not None
        delete_event(db, "evt-1")
        assert get_event(db, "evt-1") is None

    def test_delete_nonexistent_no_error(self, db: sqlite3.Connection):
        """Deleting a non-existent event should not raise an error."""
        delete_event(db, "does-not-exist")  # should not raise

    def test_upsert_replaces(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
        sample_event: ScheduledEvent,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        save_event(db, sample_event)

        updated = sample_event.model_copy(update={"notes": "Updated notes"})
        save_event(db, updated)
        loaded = get_event(db, "evt-1")
        assert loaded.notes == "Updated notes"
        assert len(list_events(db)) == 1

    def test_null_optional_fields(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        event = ScheduledEvent(
            id="evt-minimal",
            application_id="app-1",
            event_type="follow_up_due",
            scheduled_date=datetime(2025, 1, 17, 0, 0, 0),
            created_at=datetime(2025, 1, 12, 10, 0, 0),
        )
        save_event(db, event)
        loaded = get_event(db, "evt-minimal")
        assert loaded.notes is None


# ---------------------------------------------------------------------------
# Work Item CRUD
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_work_item() -> WorkItem:
    return WorkItem(
        id="wi-1",
        application_id="app-1",
        work_type=WorkType.OUTREACH,
        status=WorkStatus.PENDING,
        title="Send outreach to Acme",
        instructions="Copy the email and send it.",
        draft_content="Subject: Hi\n\nHello.",
        target_status="OUTREACH_SENT",
        previous_status="SCORED",
        created_at=datetime(2025, 2, 10, 14, 0, 0),
    )


class TestWorkItemCRUD:
    def test_save_and_get(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
        sample_work_item: WorkItem,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        save_work_item(db, sample_work_item)
        loaded = get_work_item(db, "wi-1")
        assert loaded is not None
        assert loaded.work_type == WorkType.OUTREACH
        assert loaded.status == WorkStatus.PENDING
        assert loaded.title == "Send outreach to Acme"
        assert loaded.instructions == "Copy the email and send it."
        assert loaded.draft_content == "Subject: Hi\n\nHello."
        assert loaded.target_status == "OUTREACH_SENT"
        assert loaded.previous_status == "SCORED"
        assert loaded.completed_at is None

    def test_get_nonexistent_returns_none(self, db: sqlite3.Connection):
        assert get_work_item(db, "nope") is None

    def test_list_all(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        for i in range(3):
            item = WorkItem(
                id=f"wi-{i}",
                application_id="app-1",
                work_type=WorkType.OUTREACH,
                title=f"Item {i}",
                instructions="Do it.",
                target_status="OUTREACH_SENT",
                previous_status="SCORED",
                created_at=datetime(2025, 2, 10, 14, i, 0),
            )
            save_work_item(db, item)
        assert len(list_work_items(db)) == 3

    def test_list_filter_by_status(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        for i, status in enumerate(
            [WorkStatus.PENDING, WorkStatus.COMPLETED, WorkStatus.PENDING]
        ):
            item = WorkItem(
                id=f"wi-{i}",
                application_id="app-1",
                work_type=WorkType.OUTREACH,
                status=status,
                title=f"Item {i}",
                instructions="Do it.",
                target_status="OUTREACH_SENT",
                previous_status="SCORED",
                created_at=datetime(2025, 2, 10, 14, i, 0),
            )
            save_work_item(db, item)
        pending = list_work_items(db, status=WorkStatus.PENDING)
        assert len(pending) == 2
        completed = list_work_items(db, status=WorkStatus.COMPLETED)
        assert len(completed) == 1

    def test_list_pending(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        for i, status in enumerate(
            [WorkStatus.PENDING, WorkStatus.COMPLETED, WorkStatus.SKIPPED]
        ):
            item = WorkItem(
                id=f"wi-{i}",
                application_id="app-1",
                work_type=WorkType.OUTREACH,
                status=status,
                title=f"Item {i}",
                instructions="Do it.",
                target_status="OUTREACH_SENT",
                previous_status="SCORED",
                created_at=datetime(2025, 2, 10, 14, i, 0),
            )
            save_work_item(db, item)
        pending = list_pending_work_items(db)
        assert len(pending) == 1
        assert pending[0].id == "wi-0"

    def test_upsert_updates_status(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
        sample_work_item: WorkItem,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        save_work_item(db, sample_work_item)
        updated = sample_work_item.model_copy(
            update={
                "status": WorkStatus.COMPLETED,
                "completed_at": datetime(2025, 2, 10, 15, 0, 0),
            }
        )
        save_work_item(db, updated)
        loaded = get_work_item(db, "wi-1")
        assert loaded.status == WorkStatus.COMPLETED
        assert loaded.completed_at == datetime(2025, 2, 10, 15, 0, 0)
        assert len(list_work_items(db)) == 1

    def test_null_optional_fields(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        item = WorkItem(
            id="wi-minimal",
            application_id="app-1",
            work_type=WorkType.FOLLOW_UP,
            title="Follow up",
            instructions="Do it.",
            target_status="FOLLOW_UP_1",
            previous_status="OUTREACH_SENT",
            created_at=datetime(2025, 2, 11, 8, 0, 0),
        )
        save_work_item(db, item)
        loaded = get_work_item(db, "wi-minimal")
        assert loaded.draft_content is None
        assert loaded.completed_at is None

    def test_ordered_by_created_at(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        # Insert in reverse order
        for i in [2, 0, 1]:
            item = WorkItem(
                id=f"wi-{i}",
                application_id="app-1",
                work_type=WorkType.OUTREACH,
                title=f"Item {i}",
                instructions="Do it.",
                target_status="OUTREACH_SENT",
                previous_status="SCORED",
                created_at=datetime(2025, 2, 10, 14, i, 0),
            )
            save_work_item(db, item)
        items = list_work_items(db)
        assert items[0].id == "wi-0"
        assert items[1].id == "wi-1"
        assert items[2].id == "wi-2"


# ---------------------------------------------------------------------------
# Default path
# ---------------------------------------------------------------------------


class TestStatusHistoryCRUD:
    def test_save_and_list(self, db, sample_opportunity, sample_application):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        t = StatusTransition(
            id="st-1",
            application_id=sample_application.id,
            from_status="DISCOVERED",
            to_status="SCORED",
            transitioned_at=datetime(2025, 1, 16, 10, 0, 0),
        )
        save_status_transition(db, t)
        result = list_status_transitions(db, sample_application.id)
        assert len(result) == 1
        assert result[0].from_status == "DISCOVERED"
        assert result[0].to_status == "SCORED"

    def test_ordered_by_time(self, db, sample_opportunity, sample_application):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        for i, (from_s, to_s) in enumerate(
            [
                ("DISCOVERED", "SCORED"),
                ("SCORED", "OUTREACH_PENDING"),
                ("OUTREACH_PENDING", "OUTREACH_SENT"),
            ]
        ):
            save_status_transition(
                db,
                StatusTransition(
                    id=f"st-{i}",
                    application_id=sample_application.id,
                    from_status=from_s,
                    to_status=to_s,
                    transitioned_at=datetime(2025, 1, 16, 10, i, 0),
                ),
            )
        result = list_status_transitions(db, sample_application.id)
        assert len(result) == 3
        assert result[0].to_status == "SCORED"
        assert result[2].to_status == "OUTREACH_SENT"


class TestListApplicationsByStatuses:
    def test_single_status(self, db, sample_opportunity):
        save_opportunity(db, sample_opportunity)
        app = Application(
            id="app-1",
            opportunity_id="opp-1",
            status=ApplicationStatus.OUTREACH_SENT,
            created_at=datetime(2025, 1, 15),
            updated_at=datetime(2025, 1, 15),
        )
        save_application(db, app)
        result = list_applications_by_statuses(db, [ApplicationStatus.OUTREACH_SENT])
        assert len(result) == 1
        assert result[0].id == "app-1"

    def test_multiple_statuses(self, db, sample_opportunity):
        save_opportunity(db, sample_opportunity)
        for i, status in enumerate(
            [
                ApplicationStatus.OUTREACH_SENT,
                ApplicationStatus.FOLLOW_UP_1,
                ApplicationStatus.RESPONSE_RECEIVED,
            ]
        ):
            save_application(
                db,
                Application(
                    id=f"app-{i}",
                    opportunity_id="opp-1",
                    status=status,
                    created_at=datetime(2025, 1, 15),
                    updated_at=datetime(2025, 1, 15),
                ),
            )
        result = list_applications_by_statuses(
            db,
            [
                ApplicationStatus.OUTREACH_SENT,
                ApplicationStatus.FOLLOW_UP_1,
            ],
        )
        assert len(result) == 2
        ids = {a.id for a in result}
        assert ids == {"app-0", "app-1"}

    def test_empty_or_unmatched_statuses_returns_empty(self, db, sample_opportunity):
        assert list_applications_by_statuses(db, []) == []
        save_opportunity(db, sample_opportunity)
        save_application(
            db,
            Application(
                id="app-1",
                opportunity_id="opp-1",
                status=ApplicationStatus.DISCOVERED,
                created_at=datetime(2025, 1, 15),
                updated_at=datetime(2025, 1, 15),
            ),
        )
        assert list_applications_by_statuses(db, [ApplicationStatus.ACCEPTED]) == []


class TestActiveOpportunityKeys:
    def test_scored_in_keys(self, db, sample_opportunity):
        save_opportunity(db, sample_opportunity)
        save_application(
            db,
            Application(
                id="app-active",
                opportunity_id="opp-1",
                status=ApplicationStatus.SCORED,
                created_at=datetime(2025, 1, 15),
                updated_at=datetime(2025, 1, 15),
            ),
        )
        keys = active_opportunity_keys(db)
        assert ("acme corp", "backend developer", "indeed") in keys

    def test_passed_in_keys(self, db, sample_opportunity):
        save_opportunity(db, sample_opportunity)
        save_application(
            db,
            Application(
                id="app-passed",
                opportunity_id="opp-1",
                status=ApplicationStatus.PASSED,
                created_at=datetime(2025, 1, 15),
                updated_at=datetime(2025, 1, 15),
            ),
        )
        keys = active_opportunity_keys(db)
        assert ("acme corp", "backend developer", "indeed") in keys

    def test_rejected_in_keys(self, db, sample_opportunity):
        save_opportunity(db, sample_opportunity)
        save_application(
            db,
            Application(
                id="app-rej",
                opportunity_id="opp-1",
                status=ApplicationStatus.REJECTED,
                created_at=datetime(2025, 1, 15),
                updated_at=datetime(2025, 1, 15),
            ),
        )
        keys = active_opportunity_keys(db)
        assert ("acme corp", "backend developer", "indeed") in keys

    def test_ghosted_in_keys(self, db, sample_opportunity):
        save_opportunity(db, sample_opportunity)
        save_application(
            db,
            Application(
                id="app-ghosted",
                opportunity_id="opp-1",
                status=ApplicationStatus.GHOSTED,
                created_at=datetime(2025, 1, 15),
                updated_at=datetime(2025, 1, 15),
            ),
        )
        keys = active_opportunity_keys(db)
        assert ("acme corp", "backend developer", "indeed") in keys

    def test_opportunity_without_application_not_in_keys(self, db, sample_opportunity):
        save_opportunity(db, sample_opportunity)
        keys = active_opportunity_keys(db)
        assert len(keys) == 0


class TestReclassifyThresholdApps:
    """Tests for reclassify_threshold_apps() — bulk SCORED/BELOW_THRESHOLD updates."""

    def _seed_scored_apps(self, db: sqlite3.Connection, scores: dict[str, int]) -> None:
        """Create opportunity + SCORED application per entry in *scores*."""
        now = datetime(2025, 3, 1, 10, 0, 0)
        for app_id, score in scores.items():
            opp_id = f"opp-{app_id}"
            save_opportunity(
                db,
                Opportunity(
                    id=opp_id,
                    source="test",
                    company=f"Co-{app_id}",
                    title="Dev",
                    description="D",
                    scraped_at=now,
                ),
            )
            save_application(
                db,
                Application(
                    id=app_id,
                    opportunity_id=opp_id,
                    status=ApplicationStatus.SCORED,
                    score=score,
                    created_at=now,
                    updated_at=now,
                ),
            )

    def _seed_bt_apps(self, db: sqlite3.Connection, scores: dict[str, int]) -> None:
        """Create opportunity + BELOW_THRESHOLD application per entry."""
        now = datetime(2025, 3, 1, 10, 0, 0)
        for app_id, score in scores.items():
            opp_id = f"opp-{app_id}"
            save_opportunity(
                db,
                Opportunity(
                    id=opp_id,
                    source="test",
                    company=f"Co-{app_id}",
                    title="Dev",
                    description="D",
                    scraped_at=now,
                ),
            )
            save_application(
                db,
                Application(
                    id=app_id,
                    opportunity_id=opp_id,
                    status=ApplicationStatus.BELOW_THRESHOLD,
                    score=score,
                    created_at=now,
                    updated_at=now,
                ),
            )

    def test_demotes_scored_below_threshold(self, db: sqlite3.Connection):
        """SCORED apps with score < threshold become BELOW_THRESHOLD."""
        self._seed_scored_apps(db, {"a1": 20, "a2": 25})
        changed = reclassify_threshold_apps(db, threshold=30)
        assert changed == 2
        assert get_application(db, "a1").status == ApplicationStatus.BELOW_THRESHOLD
        assert get_application(db, "a2").status == ApplicationStatus.BELOW_THRESHOLD

    def test_promotes_bt_above_threshold(self, db: sqlite3.Connection):
        """BELOW_THRESHOLD apps with score >= threshold become SCORED."""
        self._seed_bt_apps(db, {"a1": 40, "a2": 50})
        changed = reclassify_threshold_apps(db, threshold=30)
        assert changed == 2
        assert get_application(db, "a1").status == ApplicationStatus.SCORED
        assert get_application(db, "a2").status == ApplicationStatus.SCORED

    def test_no_change_when_correctly_classified(self, db: sqlite3.Connection):
        """Apps already on the right side of the threshold are untouched."""
        self._seed_scored_apps(db, {"a1": 50, "a2": 80})
        self._seed_bt_apps(db, {"a3": 10, "a4": 20})
        changed = reclassify_threshold_apps(db, threshold=30)
        assert changed == 0
        assert get_application(db, "a1").status == ApplicationStatus.SCORED
        assert get_application(db, "a3").status == ApplicationStatus.BELOW_THRESHOLD

    def test_mixed_demote_and_promote(self, db: sqlite3.Connection):
        """Both demotions and promotions happen in a single call."""
        self._seed_scored_apps(db, {"a1": 10})  # should demote
        self._seed_bt_apps(db, {"a2": 50})  # should promote
        changed = reclassify_threshold_apps(db, threshold=30)
        assert changed == 2
        assert get_application(db, "a1").status == ApplicationStatus.BELOW_THRESHOLD
        assert get_application(db, "a2").status == ApplicationStatus.SCORED

    def test_threshold_zero_promotes_all_bt(self, db: sqlite3.Connection):
        """With threshold=0, every BT app with score >= 0 is promoted."""
        self._seed_bt_apps(db, {"a1": 0, "a2": 5})
        changed = reclassify_threshold_apps(db, threshold=0)
        assert changed == 2
        assert get_application(db, "a1").status == ApplicationStatus.SCORED
        assert get_application(db, "a2").status == ApplicationStatus.SCORED

    def test_exact_threshold_boundary(self, db: sqlite3.Connection):
        """Score == threshold stays SCORED; score < threshold is demoted."""
        self._seed_scored_apps(db, {"at-boundary": 30, "below": 29})
        changed = reclassify_threshold_apps(db, threshold=30)
        assert changed == 1
        assert get_application(db, "at-boundary").status == ApplicationStatus.SCORED
        assert get_application(db, "below").status == ApplicationStatus.BELOW_THRESHOLD

    def test_ignores_non_scored_bt_statuses(self, db: sqlite3.Connection):
        """Apps in other statuses (OUTREACH_SENT, etc.) are never touched."""
        now = datetime(2025, 3, 1, 10, 0, 0)
        save_opportunity(
            db,
            Opportunity(
                id="opp-os",
                source="test",
                company="Co",
                title="Dev",
                description="D",
                scraped_at=now,
            ),
        )
        save_application(
            db,
            Application(
                id="app-os",
                opportunity_id="opp-os",
                status=ApplicationStatus.OUTREACH_SENT,
                score=10,
                created_at=now,
                updated_at=now,
            ),
        )
        changed = reclassify_threshold_apps(db, threshold=30)
        assert changed == 0
        assert get_application(db, "app-os").status == ApplicationStatus.OUTREACH_SENT

    def test_scored_with_null_score_not_demoted(self, db: sqlite3.Connection):
        """A SCORED app with no score (NULL) is not demoted."""
        now = datetime(2025, 3, 1, 10, 0, 0)
        save_opportunity(
            db,
            Opportunity(
                id="opp-null",
                source="test",
                company="Co",
                title="Dev",
                description="D",
                scraped_at=now,
            ),
        )
        save_application(
            db,
            Application(
                id="app-null",
                opportunity_id="opp-null",
                status=ApplicationStatus.SCORED,
                score=None,
                created_at=now,
                updated_at=now,
            ),
        )
        changed = reclassify_threshold_apps(db, threshold=30)
        assert changed == 0
        assert get_application(db, "app-null").status == ApplicationStatus.SCORED

    def test_bt_with_null_score_promoted(self, db: sqlite3.Connection):
        """A BELOW_THRESHOLD app with NULL score is promoted (NULL >= threshold is true)."""
        now = datetime(2025, 3, 1, 10, 0, 0)
        save_opportunity(
            db,
            Opportunity(
                id="opp-btn",
                source="test",
                company="Co",
                title="Dev",
                description="D",
                scraped_at=now,
            ),
        )
        save_application(
            db,
            Application(
                id="app-btn",
                opportunity_id="opp-btn",
                status=ApplicationStatus.BELOW_THRESHOLD,
                score=None,
                created_at=now,
                updated_at=now,
            ),
        )
        changed = reclassify_threshold_apps(db, threshold=30)
        assert changed == 1
        assert get_application(db, "app-btn").status == ApplicationStatus.SCORED

    def test_updates_updated_at_timestamp(self, db: sqlite3.Connection):
        """Reclassified apps get a fresh updated_at timestamp."""
        old_time = datetime(2025, 1, 1, 0, 0, 0)
        self._seed_scored_apps(db, {"a1": 10})
        changed = reclassify_threshold_apps(db, threshold=30)
        assert changed == 1
        loaded = get_application(db, "a1")
        assert loaded.updated_at > old_time


class TestDefaultDbPath:
    def test_returns_expected_path(self):
        p = get_default_db_path()
        assert isinstance(p, Path)
        assert p.name == "emplaiyed.db"
        assert p.parent.name == "data"


# ---------------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------------


class TestSearchOpportunities:
    """Tests for FTS5-backed opportunity search."""

    def _seed(self, db: sqlite3.Connection) -> None:
        """Insert a handful of opportunities and applications for search tests."""
        now = datetime(2025, 3, 1, 10, 0, 0)
        opps = [
            Opportunity(
                id="opp-ml",
                source="jobbank",
                company="DeepLearn Inc",
                title="Machine Learning Engineer",
                description="Build ML pipelines with PyTorch and AWS SageMaker.",
                location="Montreal, QC",
                scraped_at=now,
            ),
            Opportunity(
                id="opp-devops",
                source="indeed",
                company="CloudOps Corp",
                title="DevOps Engineer",
                description="Terraform, Kubernetes, CI/CD pipelines on AWS.",
                location="Toronto, ON",
                scraped_at=now,
            ),
            Opportunity(
                id="opp-backend",
                source="jobbank",
                company="FinTech Ltd",
                title="Senior Backend Developer",
                description="Build REST APIs in Python with FastAPI and PostgreSQL.",
                location="Ottawa, ON",
                scraped_at=now,
            ),
            Opportunity(
                id="opp-frontend",
                source="linkedin",
                company="DesignHub",
                title="Frontend Developer",
                description="React, TypeScript, CSS, build beautiful UIs.",
                location="Vancouver, BC",
                scraped_at=now,
            ),
            Opportunity(
                id="opp-noapp",
                source="manual",
                company="Orphan Co",
                title="Data Analyst",
                description="SQL, dashboards, data warehousing.",
                location="Calgary, AB",
                scraped_at=now,
            ),
        ]
        for opp in opps:
            save_opportunity(db, opp)

        # Create applications for all but the last one
        for i, opp in enumerate(opps[:-1]):
            save_application(
                db,
                Application(
                    id=f"app-{opp.id}",
                    opportunity_id=opp.id,
                    status=ApplicationStatus.SCORED,
                    score=90 - i * 10,
                    created_at=now,
                    updated_at=now,
                ),
            )

        rebuild_search_index(db)

    def test_basic_keyword_match(self, db: sqlite3.Connection) -> None:
        self._seed(db)
        results = search_opportunities(db, "DevOps")
        assert len(results) >= 1
        opps = [opp for opp, _ in results]
        assert any(o.id == "opp-devops" for o in opps)

    def test_company_search(self, db: sqlite3.Connection) -> None:
        self._seed(db)
        results = search_opportunities(db, "DeepLearn")
        assert len(results) >= 1
        assert results[0][0].id == "opp-ml"

    def test_multi_word_query(self, db: sqlite3.Connection) -> None:
        self._seed(db)
        results = search_opportunities(db, "Python FastAPI")
        assert len(results) >= 1
        opps = [opp for opp, _ in results]
        assert any(o.id == "opp-backend" for o in opps)

    def test_location_search(self, db: sqlite3.Connection) -> None:
        self._seed(db)
        results = search_opportunities(db, "Vancouver")
        assert len(results) >= 1
        assert results[0][0].id == "opp-frontend"

    def test_returns_application_when_exists(self, db: sqlite3.Connection) -> None:
        self._seed(db)
        results = search_opportunities(db, "DevOps")
        opp, app = next((o, a) for o, a in results if o.id == "opp-devops")
        assert app is not None
        assert app.id == "app-opp-devops"
        assert app.status == ApplicationStatus.SCORED

    def test_returns_none_application_when_missing(
        self, db: sqlite3.Connection
    ) -> None:
        self._seed(db)
        results = search_opportunities(db, "Data Analyst")
        opp, app = next((o, a) for o, a in results if o.id == "opp-noapp")
        assert app is None

    def test_empty_query_returns_empty(self, db: sqlite3.Connection) -> None:
        self._seed(db)
        assert search_opportunities(db, "") == []
        assert search_opportunities(db, "   ") == []

    def test_no_match_returns_empty(self, db: sqlite3.Connection) -> None:
        self._seed(db)
        results = search_opportunities(db, "xyzzyzzynonexistent")
        assert results == []

    def test_prefix_matching(self, db: sqlite3.Connection) -> None:
        """Partial words should match via the implicit prefix wildcard."""
        self._seed(db)
        results = search_opportunities(db, "Mach")
        assert len(results) >= 1
        assert any(o.id == "opp-ml" for o, _ in results)

    def test_limit_respected(self, db: sqlite3.Connection) -> None:
        self._seed(db)
        results = search_opportunities(db, "Engineer", limit=1)
        assert len(results) == 1

    def test_bad_fts_syntax_returns_empty(self, db: sqlite3.Connection) -> None:
        """Malformed FTS queries should not crash."""
        self._seed(db)
        # Unbalanced quotes are invalid FTS5 syntax
        results = search_opportunities(db, '"unclosed')
        assert results == []

    def test_rebuild_index_idempotent(self, db: sqlite3.Connection) -> None:
        """Calling rebuild multiple times should not duplicate results."""
        self._seed(db)
        rebuild_search_index(db)
        rebuild_search_index(db)
        results = search_opportunities(db, "DevOps")
        devops_results = [o for o, _ in results if o.id == "opp-devops"]
        assert len(devops_results) == 1

    def test_search_after_new_opportunity(self, db: sqlite3.Connection) -> None:
        """New opportunities are findable immediately after save (incremental index)."""
        self._seed(db)
        save_opportunity(
            db,
            Opportunity(
                id="opp-new",
                source="manual",
                company="BrandNewCo",
                title="Rust Systems Engineer",
                description="Low-level systems programming in Rust.",
                location="Remote",
                scraped_at=datetime(2025, 3, 2),
            ),
        )
        # Immediately searchable — save_opportunity indexes incrementally
        results = search_opportunities(db, "BrandNewCo")
        assert len(results) == 1
        assert results[0][0].company == "BrandNewCo"
