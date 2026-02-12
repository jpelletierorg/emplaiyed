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
    """A profile with every field populated — should produce zero gaps."""
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
        aspirations=Aspirations(
            target_roles=["Staff Engineer"],
            salary_minimum=100000,
            salary_target=130000,
            urgency="within_3_months",
            geographic_preferences=["Montreal", "Remote"],
            work_arrangement=["hybrid"],
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
        report = GapReport(
            gaps=[Gap("skills", "need skills", GapPriority.REQUIRED)]
        )
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

    def test_skills_gap_present(self, empty_profile: Profile) -> None:
        report = analyze_gaps(empty_profile)
        field_names = [g.field_name for g in report.gaps]
        assert "skills" in field_names

    def test_all_aspiration_gaps_present(self, empty_profile: Profile) -> None:
        report = analyze_gaps(empty_profile)
        field_names = [g.field_name for g in report.gaps]
        assert "aspirations.target_roles" in field_names
        assert "aspirations.salary_minimum" in field_names
        assert "aspirations.salary_target" in field_names
        assert "aspirations.urgency" in field_names
        assert "aspirations.geographic_preferences" in field_names
        assert "aspirations.work_arrangement" in field_names

    def test_nice_to_have_gaps_present(self, empty_profile: Profile) -> None:
        report = analyze_gaps(empty_profile)
        field_names = [g.field_name for g in report.gaps]
        assert "languages" in field_names
        assert "certifications" in field_names
        assert "summary" not in field_names  # summary is not stored in profile

    def test_total_gap_count(self, empty_profile: Profile) -> None:
        """Empty profile: 1 (skills) + 6 (aspirations) + 2 (nice-to-have) = 9."""
        report = analyze_gaps(empty_profile)
        assert len(report.gaps) == 9

    def test_required_gap_count(self, empty_profile: Profile) -> None:
        """Required gaps: 1 (skills) + 6 (aspirations) = 7."""
        report = analyze_gaps(empty_profile)
        assert len(report.required_gaps) == 7

    def test_nice_to_have_gap_count(self, empty_profile: Profile) -> None:
        """Nice-to-have gaps: languages + certifications = 2."""
        report = analyze_gaps(empty_profile)
        assert len(report.nice_to_have_gaps) == 2


class TestAnalyzeGapsPartial:
    """A partially filled profile should only flag missing fields."""

    def test_skills_not_flagged(self, partial_profile: Profile) -> None:
        """Skills is populated, so should not appear in gaps."""
        report = analyze_gaps(partial_profile)
        field_names = [g.field_name for g in report.gaps]
        assert "skills" not in field_names

    def test_languages_not_flagged(self, partial_profile: Profile) -> None:
        """Languages is populated."""
        report = analyze_gaps(partial_profile)
        field_names = [g.field_name for g in report.gaps]
        assert "languages" not in field_names

    def test_salary_gaps_flagged(self, partial_profile: Profile) -> None:
        """Salary fields are missing."""
        report = analyze_gaps(partial_profile)
        field_names = [g.field_name for g in report.gaps]
        assert "aspirations.salary_minimum" in field_names
        assert "aspirations.salary_target" in field_names

    def test_certifications_flagged(self, partial_profile: Profile) -> None:
        """Certifications is empty."""
        report = analyze_gaps(partial_profile)
        field_names = [g.field_name for g in report.gaps]
        assert "certifications" in field_names

    def test_populated_aspiration_fields_not_flagged(
        self, partial_profile: Profile
    ) -> None:
        """Aspiration fields that are set should not be flagged."""
        report = analyze_gaps(partial_profile)
        field_names = [g.field_name for g in report.gaps]
        assert "aspirations.target_roles" not in field_names
        assert "aspirations.urgency" not in field_names
        assert "aspirations.geographic_preferences" not in field_names
        assert "aspirations.work_arrangement" not in field_names

    def test_is_complete_false_due_to_salary(
        self, partial_profile: Profile
    ) -> None:
        """Profile is not complete because salary fields are required."""
        report = analyze_gaps(partial_profile)
        assert report.is_complete is False

    def test_gap_count(self, partial_profile: Profile) -> None:
        """2 required (salaries) + 1 nice-to-have (certifications) = 3.
        (summary is no longer a profile field, so not counted.)"""
        report = analyze_gaps(partial_profile)
        assert len(report.gaps) == 3


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

    def test_all_gaps_have_descriptions(self, empty_profile: Profile) -> None:
        """Every gap should have a non-empty description."""
        report = analyze_gaps(empty_profile)
        for gap in report.gaps:
            assert gap.description
            assert len(gap.description) > 0

    def test_all_gaps_have_valid_priority(self, empty_profile: Profile) -> None:
        """Every gap should have a valid GapPriority."""
        report = analyze_gaps(empty_profile)
        for gap in report.gaps:
            assert gap.priority in (GapPriority.REQUIRED, GapPriority.NICE_TO_HAVE)
