from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from emplaiyed.core.models import (
    Address,
    Aspirations,
    Education,
    Employment,
    Language,
    Profile,
)
from emplaiyed.core.profile_store import (
    get_default_profile_path,
    load_profile,
    save_profile,
)


@pytest.fixture
def minimal_profile() -> Profile:
    return Profile(name="Alice", email="alice@example.com")


@pytest.fixture
def full_profile() -> Profile:
    return Profile(
        name="Bob Builder",
        email="bob@example.com",
        phone="+1-555-0199",
        date_of_birth=date(1988, 7, 22),
        address=Address(
            street="456 Elm St",
            city="Montreal",
            province_state="QC",
            postal_code="H2X 1Y4",
            country="Canada",
        ),
        skills=["Python", "TypeScript", "PostgreSQL", "Docker"],
        languages=[
            Language(language="English", proficiency="fluent"),
            Language(language="French", proficiency="native"),
        ],
        education=[
            Education(
                institution="McGill University",
                degree="BSc",
                field="Computer Science",
                start_date=date(2006, 9, 1),
                end_date=date(2010, 5, 15),
            )
        ],
        employment_history=[
            Employment(
                company="TechCo",
                title="Senior Developer",
                start_date=date(2015, 3, 1),
                end_date=date(2023, 12, 31),
                description="Led backend team",
                highlights=["Reduced latency by 40%", "Mentored 5 juniors"],
            )
        ],
        aspirations=Aspirations(
            target_roles=["Staff Engineer", "Engineering Manager"],
            target_industries=["FinTech", "HealthTech"],
            salary_minimum=110000,
            salary_target=140000,
            urgency="within_3_months",
            geographic_preferences=["Montreal", "Remote"],
            work_arrangement=["hybrid"],
            statement="Looking for high-impact technical leadership roles",
        ),
    )


class TestSaveAndLoad:
    def test_round_trip_minimal(self, tmp_path: Path, minimal_profile: Profile):
        path = tmp_path / "profile.yaml"
        save_profile(minimal_profile, path)
        loaded = load_profile(path)
        assert loaded.name == minimal_profile.name
        assert loaded.email == minimal_profile.email
        assert loaded.skills == []
        assert loaded.aspirations is None

    def test_round_trip_full(self, tmp_path: Path, full_profile: Profile):
        path = tmp_path / "profile.yaml"
        save_profile(full_profile, path)
        loaded = load_profile(path)
        assert loaded.name == full_profile.name
        assert loaded.date_of_birth == full_profile.date_of_birth
        assert loaded.address.city == "Montreal"
        assert loaded.skills == full_profile.skills
        assert len(loaded.languages) == 2
        assert loaded.languages[0].language == "English"
        assert len(loaded.employment_history) == 1
        assert loaded.employment_history[0].highlights == [
            "Reduced latency by 40%",
            "Mentored 5 juniors",
        ]
        assert loaded.aspirations.salary_target == 140000
        assert loaded.aspirations.work_arrangement == ["hybrid"]

    def test_yaml_is_human_readable(self, tmp_path: Path, full_profile: Profile):
        path = tmp_path / "profile.yaml"
        save_profile(full_profile, path)
        content = path.read_text()
        # Should not be a JSON blob - should have YAML keys at top level
        assert "name:" in content
        assert "email:" in content
        assert "skills:" in content
        # Should not contain Pydantic model class names
        assert "Profile(" not in content

    def test_creates_parent_directories(self, tmp_path: Path, minimal_profile: Profile):
        path = tmp_path / "nested" / "deep" / "profile.yaml"
        save_profile(minimal_profile, path)
        assert path.exists()
        loaded = load_profile(path)
        assert loaded.name == "Alice"

    def test_dates_survive_round_trip(self, tmp_path: Path):
        p = Profile(
            name="Date Test",
            email="d@t.com",
            date_of_birth=date(1995, 12, 25),
            education=[
                Education(
                    institution="U",
                    degree="BSc",
                    field="Math",
                    start_date=date(2013, 9, 1),
                    end_date=date(2017, 6, 15),
                )
            ],
        )
        path = tmp_path / "profile.yaml"
        save_profile(p, path)
        loaded = load_profile(path)
        assert loaded.date_of_birth == date(1995, 12, 25)
        assert loaded.education[0].start_date == date(2013, 9, 1)
        assert loaded.education[0].end_date == date(2017, 6, 15)

    def test_none_fields_excluded_from_yaml(self, tmp_path: Path, minimal_profile: Profile):
        path = tmp_path / "profile.yaml"
        save_profile(minimal_profile, path)
        content = path.read_text()
        # None fields should be excluded (exclude_none=True)
        assert "phone:" not in content
        assert "date_of_birth:" not in content
        assert "aspirations:" not in content


class TestLoadErrors:
    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_profile(tmp_path / "nonexistent.yaml")

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_profile(path)

    def test_invalid_yaml_missing_required(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("skills:\n  - Python\n")
        with pytest.raises(Exception):
            load_profile(path)


class TestDefaultPath:
    def test_returns_path_object(self):
        p = get_default_profile_path()
        assert isinstance(p, Path)

    def test_ends_with_expected_path(self):
        p = get_default_profile_path()
        assert p.name == "profile.yaml"
        assert p.parent.name == "data"
