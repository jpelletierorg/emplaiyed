from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from emplaiyed.core.database import (
    delete_event,
    get_default_db_path,
    get_application,
    get_event,
    get_offer,
    get_opportunity,
    get_work_item,
    init_db,
    list_applications,
    list_events,
    list_interactions,
    list_offers,
    list_opportunities,
    list_pending_work_items,
    list_upcoming_events,
    list_work_items,
    save_application,
    save_event,
    save_interaction,
    save_offer,
    save_opportunity,
    save_work_item,
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
    WorkItem,
    WorkStatus,
    WorkType,
)


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


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

    def test_idempotent(self, tmp_path: Path):
        """Calling init_db twice on the same path should not error."""
        db_path = tmp_path / "test.db"
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        conn2.close()

    def test_migration_adds_scoring_columns(self, tmp_path: Path):
        """Migrations add scoring columns to applications table."""
        db_path = tmp_path / "migrate.db"
        conn = init_db(db_path)
        # Verify the columns exist by inserting a row with scoring data
        app = Application(
            id="app-m",
            opportunity_id="opp-m",
            status=ApplicationStatus.SCORED,
            score=75,
            justification="Good fit",
            day_to_day="Write code daily",
            why_it_fits="Skills align",
            created_at=datetime(2025, 1, 1, 0, 0, 0),
            updated_at=datetime(2025, 1, 1, 0, 0, 0),
        )
        # Need an opportunity first (FK)
        save_opportunity(conn, Opportunity(
            id="opp-m", source="test", company="Co", title="Dev",
            description="D", scraped_at=datetime(2025, 1, 1, 0, 0, 0),
        ))
        save_application(conn, app)
        loaded = get_application(conn, "app-m")
        assert loaded.score == 75
        conn.close()

    def test_migration_idempotent(self, tmp_path: Path):
        """Running init_db twice does not fail on already-added columns."""
        db_path = tmp_path / "idempotent.db"
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        # Should not raise
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
        assert loaded.raw_data == {"original_id": "abc123", "tags": ["python", "remote"]}

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
        updated = sample_opportunity.model_copy(update={"title": "Senior Backend Developer"})
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
        self, db: sqlite3.Connection, sample_opportunity: Opportunity, sample_application: Application
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        loaded = get_application(db, "app-1")
        assert loaded is not None
        assert loaded.opportunity_id == "opp-1"
        assert loaded.status == ApplicationStatus.DISCOVERED

    def test_get_nonexistent_returns_none(self, db: sqlite3.Connection):
        assert get_application(db, "nope") is None

    def test_list_all(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity
    ):
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
            [ApplicationStatus.DISCOVERED, ApplicationStatus.SCORED, ApplicationStatus.DISCOVERED]
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
        assert loaded.why_it_fits == "Deep Python and cloud experience aligns perfectly."

    def test_scoring_fields_default_to_none(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity, sample_application: Application
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)
        loaded = get_application(db, "app-1")
        assert loaded.score is None
        assert loaded.justification is None
        assert loaded.day_to_day is None
        assert loaded.why_it_fits is None

    def test_upsert_updates_status(
        self, db: sqlite3.Connection, sample_opportunity: Opportunity, sample_application: Application
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

    def test_list_empty(self, db: sqlite3.Connection):
        assert list_interactions(db, "no-app") == []

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
        for i, status in enumerate([OfferStatus.PENDING, OfferStatus.ACCEPTED, OfferStatus.PENDING]):
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

        save_event(db, ScheduledEvent(
            id="evt-a1",
            application_id="app-a",
            event_type="phone_screen",
            scheduled_date=datetime(2025, 1, 14, 14, 0, 0),
            created_at=datetime(2025, 1, 12, 10, 0, 0),
        ))
        save_event(db, ScheduledEvent(
            id="evt-b1",
            application_id="app-b",
            event_type="technical_interview",
            scheduled_date=datetime(2025, 1, 15, 10, 0, 0),
            created_at=datetime(2025, 1, 12, 10, 0, 0),
        ))
        save_event(db, ScheduledEvent(
            id="evt-a2",
            application_id="app-a",
            event_type="onsite",
            scheduled_date=datetime(2025, 1, 20, 9, 0, 0),
            created_at=datetime(2025, 1, 12, 10, 0, 0),
        ))

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
            save_event(db, ScheduledEvent(
                id=f"evt-jan{day}",
                application_id="app-1",
                event_type="phone_screen",
                scheduled_date=datetime(2025, 1, day, 14, 0, 0),
                created_at=datetime(2025, 1, 8, 10, 0, 0),
            ))

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
            save_event(db, ScheduledEvent(
                id=f"evt-jan{day}",
                application_id="app-1",
                event_type="phone_screen",
                scheduled_date=datetime(2025, 1, day, 14, 0, 0),
                created_at=datetime(2025, 1, 8, 10, 0, 0),
            ))

        events = list_events(db)
        assert len(events) == 3
        assert events[0].scheduled_date < events[1].scheduled_date < events[2].scheduled_date

    def test_list_upcoming_only_future(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)

        # Create a past event and a future event
        save_event(db, ScheduledEvent(
            id="evt-past",
            application_id="app-1",
            event_type="phone_screen",
            scheduled_date=datetime(2020, 1, 1, 10, 0, 0),  # clearly in the past
            created_at=datetime(2019, 12, 28, 10, 0, 0),
        ))
        save_event(db, ScheduledEvent(
            id="evt-future",
            application_id="app-1",
            event_type="technical_interview",
            scheduled_date=datetime(2099, 12, 31, 10, 0, 0),  # clearly in the future
            created_at=datetime(2099, 12, 1, 10, 0, 0),
        ))

        upcoming = list_upcoming_events(db)
        assert len(upcoming) == 1
        assert upcoming[0].id == "evt-future"

    def test_list_upcoming_sorted_by_date(
        self,
        db: sqlite3.Connection,
        sample_opportunity: Opportunity,
        sample_application: Application,
    ):
        save_opportunity(db, sample_opportunity)
        save_application(db, sample_application)

        # Insert future events in reverse order
        for year in [2099, 2098, 2097]:
            save_event(db, ScheduledEvent(
                id=f"evt-{year}",
                application_id="app-1",
                event_type="phone_screen",
                scheduled_date=datetime(year, 6, 15, 10, 0, 0),
                created_at=datetime(year, 6, 1, 10, 0, 0),
            ))

        upcoming = list_upcoming_events(db)
        assert len(upcoming) == 3
        assert upcoming[0].scheduled_date < upcoming[1].scheduled_date < upcoming[2].scheduled_date

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
        for i, status in enumerate([WorkStatus.PENDING, WorkStatus.COMPLETED, WorkStatus.PENDING]):
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
        for i, status in enumerate([WorkStatus.PENDING, WorkStatus.COMPLETED, WorkStatus.SKIPPED]):
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


class TestDefaultDbPath:
    def test_returns_path_object(self):
        p = get_default_db_path()
        assert isinstance(p, Path)

    def test_ends_with_expected_path(self):
        p = get_default_db_path()
        assert p.name == "emplaiyed.db"
        assert p.parent.name == "data"
