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
    def _make_opportunity(self) -> Opportunity:
        return Opportunity(
            source="manual",
            company="X",
            title="Y",
            description="Z",
            scraped_at=datetime.now(),
        )

    def test_valid_score(self):
        scored = ScoredOpportunity(
            opportunity=self._make_opportunity(),
            score=85,
            justification="Great match",
        )
        assert scored.score == 85

    @pytest.mark.parametrize("bad_score", [101, -1])
    def test_score_out_of_bounds_rejected(self, bad_score: int):
        with pytest.raises(ValidationError):
            ScoredOpportunity(
                opportunity=self._make_opportunity(),
                score=bad_score,
                justification="Invalid",
            )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    @pytest.mark.parametrize(
        "enum_cls, member, expected_value",
        [
            (ApplicationStatus, "DISCOVERED", "DISCOVERED"),
            (ApplicationStatus, "GHOSTED", "GHOSTED"),
            (InteractionType, "EMAIL_SENT", "EMAIL_SENT"),
            (OfferStatus, "PENDING", "PENDING"),
            (OfferStatus, "COUNTERED", "COUNTERED"),
        ],
    )
    def test_enum_values(self, enum_cls, member: str, expected_value: str):
        assert enum_cls[member].value == expected_value

    @pytest.mark.parametrize(
        "enum_cls, expected_len",
        [
            (ApplicationStatus, 19),
            (InteractionType, 8),
            (OfferStatus, 5),
        ],
    )
    def test_enum_member_counts(self, enum_cls, expected_len: int):
        assert len(enum_cls) == expected_len

    @pytest.mark.parametrize(
        "enum_member, string_value",
        [
            (ApplicationStatus.DISCOVERED, "DISCOVERED"),
            (InteractionType.NOTE, "NOTE"),
            (OfferStatus.ACCEPTED, "ACCEPTED"),
        ],
    )
    def test_str_enum_equals_string(self, enum_member, string_value: str):
        """str enums should compare equal to their string values."""
        assert enum_member == string_value


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class TestApplication:
    def test_status_transition(self):
        now = datetime.now()
        app = Application(
            opportunity_id="opp-1",
            status=ApplicationStatus.DISCOVERED,
            created_at=now,
            updated_at=now,
        )
        assert app.id  # uuid generated
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

    @pytest.mark.parametrize(
        "event_type",
        ["phone_screen", "technical_interview", "onsite", "follow_up_due"],
    )
    def test_various_event_types(self, event_type: str):
        """Different event types should all be valid strings."""
        event = ScheduledEvent(
            application_id="app-1",
            event_type=event_type,
            scheduled_date=datetime(2025, 1, 20, 10, 0, 0),
            created_at=datetime.now(),
        )
        assert event.event_type == event_type
