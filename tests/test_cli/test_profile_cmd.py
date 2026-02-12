"""Tests for the profile CLI subcommands."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from emplaiyed.core.models import (
    Address,
    Aspirations,
    Education,
    Employment,
    Language,
    Profile,
)
from emplaiyed.core.profile_store import save_profile
from emplaiyed.main import app

runner = CliRunner()


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


class TestProfileShow:
    def test_no_profile_shows_helpful_message(self, tmp_path: Path):
        fake_path = tmp_path / "nonexistent" / "profile.yaml"
        with patch(
            "emplaiyed.cli.profile_cmd.get_default_profile_path",
            return_value=fake_path,
        ):
            result = runner.invoke(app, ["profile", "show"])
        assert result.exit_code == 0
        assert "No profile found" in result.output
        assert "profile build" in result.output

    def test_show_with_valid_profile(self, tmp_path: Path, full_profile: Profile):
        path = tmp_path / "profile.yaml"
        save_profile(full_profile, path)
        with patch(
            "emplaiyed.cli.profile_cmd.get_default_profile_path",
            return_value=path,
        ):
            result = runner.invoke(app, ["profile", "show"])
        assert result.exit_code == 0
        assert "Bob Builder" in result.output
        assert "bob@example.com" in result.output
        assert "Python" in result.output
        assert "TypeScript" in result.output
        assert "TechCo" in result.output
        assert "Senior Developer" in result.output
        assert "McGill University" in result.output
        assert "Staff Engineer" in result.output

    def test_show_minimal_profile(self, tmp_path: Path):
        profile = Profile(name="Alice", email="alice@example.com")
        path = tmp_path / "profile.yaml"
        save_profile(profile, path)
        with patch(
            "emplaiyed.cli.profile_cmd.get_default_profile_path",
            return_value=path,
        ):
            result = runner.invoke(app, ["profile", "show"])
        assert result.exit_code == 0
        assert "Alice" in result.output
        assert "alice@example.com" in result.output


class TestProfilePath:
    def test_returns_path_string(self):
        result = runner.invoke(app, ["profile", "path"])
        assert result.exit_code == 0
        assert "profile.yaml" in result.output

    def test_returns_absolute_path(self):
        result = runner.invoke(app, ["profile", "path"])
        assert result.exit_code == 0
        # The path should contain the data directory
        output = result.output.strip()
        assert "data" in output
