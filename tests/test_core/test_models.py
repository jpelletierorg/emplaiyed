from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from emplaiyed.core.models import (
    Address,
    Application,
    ApplicationStatus,
    Aspirations,
    Certification,
    Education,
    Employment,
    Interaction,
    InteractionType,
    Language,
    Offer,
    OfferStatus,
    Opportunity,
    Profile,
    ScheduledEvent,
    ScoredOpportunity,
    SmtpConfig,
)


# ---------------------------------------------------------------------------
# Profile and sub-models
# ---------------------------------------------------------------------------


class TestProfile:
    def test_minimal_profile(self):
        p = Profile(name="Alice", email="alice@example.com")
        assert p.name == "Alice"
        assert p.email == "alice@example.com"
        assert p.phone is None
        assert p.skills == []
        assert p.education == []
        assert p.employment_history == []
        assert p.aspirations is None
        assert p.smtp_config is None

    def test_full_profile(self):
        p = Profile(
            name="Bob",
            email="bob@example.com",
            phone="+1-555-1234",
            date_of_birth=date(1990, 5, 15),
            address=Address(
                street="123 Main St",
                city="Quebec City",
                province_state="QC",
                postal_code="G1A 1A1",
                country="Canada",
            ),
            skills=["Python", "SQL"],
            languages=[Language(language="French", proficiency="native")],
            education=[
                Education(
                    institution="Laval",
                    degree="BSc",
                    field="CS",
                    start_date=date(2008, 9, 1),
                    end_date=date(2012, 6, 1),
                )
            ],
            employment_history=[
                Employment(
                    company="Acme",
                    title="Dev",
                    start_date=date(2012, 7, 1),
                    description="Built things",
                    highlights=["Shipped v2"],
                )
            ],
            certifications=[
                Certification(
                    name="AWS SAA",
                    issuer="Amazon",
                    date_obtained=date(2023, 1, 1),
                    expiry_date=date(2026, 1, 1),
                )
            ],
            aspirations=Aspirations(
                target_roles=["Senior Dev"],
                salary_target=120000,
                urgency="immediate",
                geographic_preferences=["Remote"],
                work_arrangement=["remote"],
            ),
            smtp_config=SmtpConfig(
                host="smtp.example.com",
                port=587,
                user="bob",
                password="secret",
                from_address="bob@example.com",
            ),
        )
        assert p.address.city == "Quebec City"
        assert p.aspirations.urgency == "immediate"
        assert p.smtp_config.port == 587
        assert len(p.employment_history[0].highlights) == 1

    def test_name_required(self):
        with pytest.raises(ValidationError):
            Profile(email="a@b.com")  # type: ignore[call-arg]

    def test_email_required(self):
        with pytest.raises(ValidationError):
            Profile(name="Alice")  # type: ignore[call-arg]

    def test_serialization_round_trip(self):
        p = Profile(
            name="Carol",
            email="carol@x.com",
            skills=["Go", "Rust"],
            date_of_birth=date(1985, 3, 20),
        )
        data = p.model_dump()
        p2 = Profile.model_validate(data)
        assert p2.name == p.name
        assert p2.date_of_birth == p.date_of_birth
        assert p2.skills == p.skills


# ---------------------------------------------------------------------------
# Opportunity
# ---------------------------------------------------------------------------


class TestOpportunity:
    def test_creation_with_defaults(self):
        now = datetime(2025, 1, 15, 10, 0, 0)
        opp = Opportunity(
            source="indeed",
            company="Acme",
            title="Dev",
            description="Build things",
            scraped_at=now,
        )
        assert opp.id  # uuid was generated
        assert opp.source == "indeed"
        assert opp.source_url is None
        assert opp.raw_data is None

    def test_full_opportunity(self):
        now = datetime(2025, 1, 15, 10, 0, 0)
        opp = Opportunity(
            id="custom-id",
            source="linkedin",
            source_url="https://linkedin.com/jobs/123",
            company="BigCorp",
            title="Senior Dev",
            description="We need someone great",
            location="Montreal",
            salary_min=90000,
            salary_max=120000,
            posted_date=date(2025, 1, 10),
            scraped_at=now,
            raw_data={"original_field": "value"},
        )
        assert opp.id == "custom-id"
        assert opp.salary_min == 90000


# ---------------------------------------------------------------------------
# ScoredOpportunity
# ---------------------------------------------------------------------------


class TestScoredOpportunity:
    def test_valid_score(self):
        opp = Opportunity(
            source="manual",
            company="X",
            title="Y",
            description="Z",
            scraped_at=datetime.now(),
        )
        scored = ScoredOpportunity(
            opportunity=opp, score=85, justification="Great match"
        )
        assert scored.score == 85

    def test_score_bounds(self):
        opp = Opportunity(
            source="manual",
            company="X",
            title="Y",
            description="Z",
            scraped_at=datetime.now(),
        )
        with pytest.raises(ValidationError):
            ScoredOpportunity(opportunity=opp, score=101, justification="Too high")
        with pytest.raises(ValidationError):
            ScoredOpportunity(opportunity=opp, score=-1, justification="Too low")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_application_status_values(self):
        assert ApplicationStatus.DISCOVERED.value == "DISCOVERED"
        assert ApplicationStatus.GHOSTED.value == "GHOSTED"
        assert len(ApplicationStatus) == 18

    def test_interaction_type_values(self):
        assert InteractionType.EMAIL_SENT.value == "EMAIL_SENT"
        assert len(InteractionType) == 8

    def test_offer_status_values(self):
        assert OfferStatus.PENDING.value == "PENDING"
        assert OfferStatus.COUNTERED.value == "COUNTERED"
        assert len(OfferStatus) == 5

    def test_enum_string_comparison(self):
        """str enums should compare equal to their string values."""
        assert ApplicationStatus.DISCOVERED == "DISCOVERED"
        assert InteractionType.NOTE == "NOTE"
        assert OfferStatus.ACCEPTED == "ACCEPTED"


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class TestApplication:
    def test_creation(self):
        now = datetime.now()
        app = Application(
            opportunity_id="opp-1",
            status=ApplicationStatus.DISCOVERED,
            created_at=now,
            updated_at=now,
        )
        assert app.id  # uuid generated
        assert app.status == ApplicationStatus.DISCOVERED

    def test_status_transition(self):
        now = datetime.now()
        app = Application(
            opportunity_id="opp-1",
            status=ApplicationStatus.DISCOVERED,
            created_at=now,
            updated_at=now,
        )
        app.status = ApplicationStatus.SCORED
        assert app.status == ApplicationStatus.SCORED


# ---------------------------------------------------------------------------
# Interaction
# ---------------------------------------------------------------------------


class TestInteraction:
    def test_creation(self):
        now = datetime.now()
        i = Interaction(
            application_id="app-1",
            type=InteractionType.EMAIL_SENT,
            direction="outbound",
            channel="email",
            content="Hello, I am interested in the position.",
            metadata={"thread_id": "abc"},
            created_at=now,
        )
        assert i.direction == "outbound"
        assert i.metadata["thread_id"] == "abc"

    def test_optional_fields(self):
        now = datetime.now()
        i = Interaction(
            application_id="app-1",
            type=InteractionType.NOTE,
            direction="outbound",
            channel="internal",
            created_at=now,
        )
        assert i.content is None
        assert i.metadata is None


# ---------------------------------------------------------------------------
# Offer
# ---------------------------------------------------------------------------


class TestOffer:
    def test_creation(self):
        now = datetime.now()
        o = Offer(
            application_id="app-1",
            salary=100000,
            benefits="Full health",
            start_date=date(2025, 3, 1),
            deadline=date(2025, 2, 15),
            status=OfferStatus.PENDING,
            created_at=now,
        )
        assert o.currency == "CAD"
        assert o.salary == 100000

    def test_default_currency(self):
        now = datetime.now()
        o = Offer(
            application_id="app-1",
            status=OfferStatus.PENDING,
            created_at=now,
        )
        assert o.currency == "CAD"
        assert o.salary is None

    def test_serialization(self):
        now = datetime.now()
        o = Offer(
            application_id="app-1",
            salary=90000,
            status=OfferStatus.ACCEPTED,
            created_at=now,
        )
        data = o.model_dump()
        o2 = Offer.model_validate(data)
        assert o2.salary == o.salary
        assert o2.status == OfferStatus.ACCEPTED


# ---------------------------------------------------------------------------
# ScheduledEvent
# ---------------------------------------------------------------------------


class TestScheduledEvent:
    def test_creation_with_defaults(self):
        now = datetime.now()
        event = ScheduledEvent(
            application_id="app-1",
            event_type="phone_screen",
            scheduled_date=datetime(2025, 1, 14, 14, 0, 0),
            created_at=now,
        )
        assert event.id  # uuid was generated
        assert event.application_id == "app-1"
        assert event.event_type == "phone_screen"
        assert event.scheduled_date == datetime(2025, 1, 14, 14, 0, 0)
        assert event.notes is None
        assert event.created_at == now

    def test_creation_with_all_fields(self):
        now = datetime.now()
        event = ScheduledEvent(
            id="evt-custom",
            application_id="app-1",
            event_type="technical_interview",
            scheduled_date=datetime(2025, 1, 16, 10, 0, 0),
            notes="With Sarah Chen, Talent Acquisition",
            created_at=now,
        )
        assert event.id == "evt-custom"
        assert event.notes == "With Sarah Chen, Talent Acquisition"

    def test_custom_id(self):
        now = datetime.now()
        event = ScheduledEvent(
            id="my-custom-id",
            application_id="app-1",
            event_type="onsite",
            scheduled_date=datetime(2025, 2, 1, 9, 0, 0),
            created_at=now,
        )
        assert event.id == "my-custom-id"

    def test_serialization_round_trip(self):
        now = datetime.now()
        event = ScheduledEvent(
            application_id="app-1",
            event_type="follow_up_due",
            scheduled_date=datetime(2025, 1, 17, 0, 0, 0),
            notes="Send a reminder email",
            created_at=now,
        )
        data = event.model_dump()
        event2 = ScheduledEvent.model_validate(data)
        assert event2.application_id == event.application_id
        assert event2.event_type == event.event_type
        assert event2.scheduled_date == event.scheduled_date
        assert event2.notes == event.notes
        assert event2.created_at == event.created_at

    def test_various_event_types(self):
        """Different event types should all be valid strings."""
        now = datetime.now()
        for event_type in ["phone_screen", "technical_interview", "onsite", "follow_up_due"]:
            event = ScheduledEvent(
                application_id="app-1",
                event_type=event_type,
                scheduled_date=datetime(2025, 1, 20, 10, 0, 0),
                created_at=now,
            )
            assert event.event_type == event_type
