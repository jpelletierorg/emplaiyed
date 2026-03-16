"""Tests for emplaiyed.profile.gap_analyzer."""

from __future__ import annotations

from datetime import date

import pytest

from emplaiyed.core.models import (
    Address,
    Aspirations,
    Certification,
    Education,
    Employment,
    Language,
    Profile,
    Project,
)
from emplaiyed.profile.gap_analyzer import (
    Gap,
    GapPriority,
    GapReport,
    analyze_gaps,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def full_profile() -> Profile:
    """A profile with every field populated -- should produce zero gaps."""
    return Profile(
        name="Alice Smith",
        email="alice@example.com",
        phone="+1-555-0100",
        date_of_birth=date(1990, 1, 1),
        address=Address(city="Montreal", province_state="QC", country="Canada"),
        skills=["Python", "Go", "PostgreSQL", "Docker"],
        languages=[
            Language(language="English", proficiency="native"),
            Language(language="French", proficiency="fluent"),
        ],
        education=[
            Education(
                institution="MIT",
                degree="BSc",
                field="CS",
                start_date=date(2008, 9, 1),
                end_date=date(2012, 6, 1),
            ),
        ],
        employment_history=[
            Employment(
                company="BigCo",
                title="Senior Engineer",
                start_date=date(2015, 1, 1),
            ),
        ],
        certifications=[
            Certification(name="AWS SAA", issuer="Amazon"),
        ],
        projects=[
            Project(
                name="emplaiyed", description="AI job toolkit", technologies=["Python"]
            ),
        ],
        aspirations=Aspirations(
            target_roles=["Staff Engineer"],
            salary_minimum=100000,
            salary_target=130000,
            urgency="within_3_months",
            geographic_preferences=["Montreal", "Remote"],
            work_arrangement=["hybrid"],
            statement="I want to lead teams building scalable distributed systems.",
        ),
    )


@pytest.fixture
def empty_profile() -> Profile:
    """A profile with only required Pydantic fields (name, email)."""
    return Profile(name="Bob", email="bob@example.com")


@pytest.fixture
def partial_profile() -> Profile:
    """A profile with some fields populated but gaps remaining."""
    return Profile(
        name="Carol",
        email="carol@example.com",
        skills=["Python", "TypeScript"],
        languages=[Language(language="English", proficiency="native")],
        aspirations=Aspirations(
            target_roles=["Backend Engineer"],
            # salary_minimum missing
            # salary_target missing
            urgency="not_urgent",
            geographic_preferences=["Remote"],
            work_arrangement=["remote"],
        ),
    )


# ---------------------------------------------------------------------------
# GapReport dataclass tests
# ---------------------------------------------------------------------------


class TestGapReport:
    def test_empty_report_is_complete(self) -> None:
        report = GapReport(gaps=[])
        assert report.is_complete is True
        assert report.is_fully_complete is True

    def test_required_gaps_make_incomplete(self) -> None:
        report = GapReport(gaps=[Gap("skills", "need skills", GapPriority.REQUIRED)])
        assert report.is_complete is False
        assert report.is_fully_complete is False

    def test_nice_to_have_only_is_complete(self) -> None:
        report = GapReport(
            gaps=[Gap("languages", "need languages", GapPriority.NICE_TO_HAVE)]
        )
        assert report.is_complete is True
        assert report.is_fully_complete is False

    def test_required_gaps_filter(self) -> None:
        report = GapReport(
            gaps=[
                Gap("skills", "need skills", GapPriority.REQUIRED),
                Gap("languages", "need languages", GapPriority.NICE_TO_HAVE),
            ]
        )
        assert len(report.required_gaps) == 1
        assert len(report.nice_to_have_gaps) == 1
        assert report.required_gaps[0].field_name == "skills"
        assert report.nice_to_have_gaps[0].field_name == "languages"


# ---------------------------------------------------------------------------
# analyze_gaps tests
# ---------------------------------------------------------------------------


class TestAnalyzeGapsFull:
    """A fully populated profile should have no gaps."""

    def test_no_gaps(self, full_profile: Profile) -> None:
        report = analyze_gaps(full_profile)
        assert report.is_fully_complete is True
        assert len(report.gaps) == 0


class TestAnalyzeGapsEmpty:
    """An empty (minimal) profile should have all gaps."""

    def test_has_required_gaps(self, empty_profile: Profile) -> None:
        report = analyze_gaps(empty_profile)
        assert report.is_complete is False

    @pytest.mark.parametrize(
        "expected_field",
        [
            "skills",
            "aspirations.target_roles",
            "aspirations.salary_minimum",
            "aspirations.salary_target",
            "aspirations.urgency",
            "aspirations.geographic_preferences",
            "aspirations.work_arrangement",
            "aspirations.statement",
            "languages",
            "certifications",
            "projects",
        ],
        ids=[
            "skills",
            "target_roles",
            "salary_minimum",
            "salary_target",
            "urgency",
            "geographic_preferences",
            "work_arrangement",
            "statement",
            "languages",
            "certifications",
            "projects",
        ],
    )
    def test_gap_present(self, empty_profile: Profile, expected_field: str) -> None:
        """Each expected gap field should appear in the empty profile report."""
        report = analyze_gaps(empty_profile)
        field_names = [g.field_name for g in report.gaps]
        assert expected_field in field_names

    def test_summary_not_in_gaps(self, empty_profile: Profile) -> None:
        """Summary is derived, not stored -- should never appear as a gap."""
        report = analyze_gaps(empty_profile)
        field_names = [g.field_name for g in report.gaps]
        assert "summary" not in field_names

    def test_total_gap_count(self, empty_profile: Profile) -> None:
        """Empty profile: 1 (skills) + 7 (aspirations incl. statement) + 3 (nice-to-have) = 11."""
        report = analyze_gaps(empty_profile)
        assert len(report.gaps) == 11

    def test_required_gap_count(self, empty_profile: Profile) -> None:
        """Required gaps: 1 (skills) + 7 (aspirations incl. statement) = 8."""
        report = analyze_gaps(empty_profile)
        assert len(report.required_gaps) == 8

    def test_nice_to_have_gap_count(self, empty_profile: Profile) -> None:
        """Nice-to-have gaps: languages + certifications + projects = 3."""
        report = analyze_gaps(empty_profile)
        assert len(report.nice_to_have_gaps) == 3


class TestAnalyzeGapsPartial:
    """A partially filled profile should only flag missing fields."""

    @pytest.mark.parametrize(
        "field_name",
        [
            "aspirations.salary_minimum",
            "aspirations.salary_target",
            "certifications",
        ],
        ids=["salary_minimum", "salary_target", "certifications"],
    )
    def test_missing_fields_flagged(
        self, partial_profile: Profile, field_name: str
    ) -> None:
        """Fields that are missing should appear in gaps."""
        report = analyze_gaps(partial_profile)
        field_names = [g.field_name for g in report.gaps]
        assert field_name in field_names

    @pytest.mark.parametrize(
        "field_name",
        [
            "skills",
            "languages",
            "aspirations.target_roles",
            "aspirations.urgency",
            "aspirations.geographic_preferences",
            "aspirations.work_arrangement",
        ],
        ids=[
            "skills",
            "languages",
            "target_roles",
            "urgency",
            "geographic_preferences",
            "work_arrangement",
        ],
    )
    def test_populated_fields_not_flagged(
        self, partial_profile: Profile, field_name: str
    ) -> None:
        """Fields that are populated should not appear in gaps."""
        report = analyze_gaps(partial_profile)
        field_names = [g.field_name for g in report.gaps]
        assert field_name not in field_names

    def test_is_complete_false_due_to_salary(self, partial_profile: Profile) -> None:
        """Profile is not complete because salary fields are required."""
        report = analyze_gaps(partial_profile)
        assert report.is_complete is False

    def test_gap_count(self, partial_profile: Profile) -> None:
        """3 required (salaries + statement) + 2 nice-to-have (certifications + projects) = 5."""
        report = analyze_gaps(partial_profile)
        assert len(report.gaps) == 5


class TestAnalyzeGapsEdgeCases:
    """Edge cases in gap detection."""

    def test_aspirations_with_empty_target_roles(self) -> None:
        """Aspirations object present but target_roles is empty list."""
        profile = Profile(
            name="Test",
            email="test@example.com",
            skills=["Python"],
            aspirations=Aspirations(
                target_roles=[],
                salary_minimum=80000,
                salary_target=100000,
                urgency="urgent",
                geographic_preferences=["Remote"],
                work_arrangement=["remote"],
            ),
        )
        report = analyze_gaps(profile)
        field_names = [g.field_name for g in report.gaps]
        assert "aspirations.target_roles" in field_names

    def test_empty_skills_list_is_flagged(self) -> None:
        """An empty skills list should be flagged as a gap."""
        profile = Profile(
            name="Test",
            email="test@example.com",
            skills=[],
        )
        report = analyze_gaps(profile)
        field_names = [g.field_name for g in report.gaps]
        assert "skills" in field_names
