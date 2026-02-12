"""Tests for emplaiyed.profile.builder — the conversational profile builder.

All tests use TestModel to avoid real API calls and inject scripted user
input via prompt_fn / print_fn callables.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterator

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.models import (
    Address,
    Aspirations,
    Education,
    Employment,
    Language,
    Profile,
)
from emplaiyed.core.profile_store import load_profile, save_profile
from emplaiyed.profile.builder import (
    _group_questions,
    _merge_profiles,
    build_profile,
    format_profile_summary,
)
from emplaiyed.profile.gap_analyzer import (
    Gap,
    GapPriority,
    GapReport,
    analyze_gaps,
)


# ---------------------------------------------------------------------------
# Helpers for scripting user input
# ---------------------------------------------------------------------------

class ScriptedIO:
    """Simulates user input from a pre-defined list of responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses: Iterator[str] = iter(responses)
        self.printed: list[str] = []

    def prompt(self, message: str) -> str:
        self.printed.append(f"[PROMPT] {message}")
        try:
            return next(self._responses)
        except StopIteration:
            raise AssertionError(
                f"ScriptedIO ran out of responses. Last prompt: {message}"
            )

    def display(self, message: str) -> None:
        self.printed.append(message)


# ---------------------------------------------------------------------------
# _merge_profiles tests
# ---------------------------------------------------------------------------

class TestMergeProfiles:
    def test_update_overwrites_scalars(self) -> None:
        base = Profile(name="Old Name", email="old@example.com")
        update = Profile(name="New Name", email="new@example.com")
        merged = _merge_profiles(base, update)
        assert merged.name == "New Name"
        assert merged.email == "new@example.com"

    def test_base_preserved_when_update_is_default(self) -> None:
        base = Profile(
            name="Alice",
            email="alice@example.com",
            phone="+1-555-0100",
            skills=["Python", "Go"],
        )
        update = Profile(name="Alice", email="alice@example.com")
        merged = _merge_profiles(base, update)
        assert merged.phone == "+1-555-0100"
        assert merged.skills == ["Python", "Go"]

    def test_update_list_wins_when_non_empty(self) -> None:
        base = Profile(
            name="Alice",
            email="alice@example.com",
            skills=["Python"],
        )
        update = Profile(
            name="Alice",
            email="alice@example.com",
            skills=["Python", "Go", "Rust"],
        )
        merged = _merge_profiles(base, update)
        assert merged.skills == ["Python", "Go", "Rust"]

    def test_base_list_preserved_when_update_empty(self) -> None:
        base = Profile(
            name="Alice",
            email="alice@example.com",
            skills=["Python", "Go"],
        )
        update = Profile(
            name="Alice",
            email="alice@example.com",
            skills=[],
        )
        merged = _merge_profiles(base, update)
        assert merged.skills == ["Python", "Go"]

    def test_sub_model_merge(self) -> None:
        base = Profile(
            name="Alice",
            email="alice@example.com",
            aspirations=Aspirations(
                target_roles=["Engineer"],
                salary_minimum=80000,
            ),
        )
        update = Profile(
            name="Alice",
            email="alice@example.com",
            aspirations=Aspirations(
                target_roles=["Staff Engineer"],
                salary_target=120000,
            ),
        )
        merged = _merge_profiles(base, update)
        assert merged.aspirations is not None
        # Update's non-None values should win
        assert merged.aspirations.salary_target == 120000
        # target_roles from update is non-empty, so it wins
        assert merged.aspirations.target_roles == ["Staff Engineer"]


# ---------------------------------------------------------------------------
# format_profile_summary tests
# ---------------------------------------------------------------------------

class TestFormatProfileSummary:
    def test_minimal_profile(self) -> None:
        p = Profile(name="Bob", email="bob@example.com")
        summary = format_profile_summary(p)
        assert "Bob" in summary
        assert "bob@example.com" in summary

    def test_includes_skills(self) -> None:
        p = Profile(
            name="Bob",
            email="bob@example.com",
            skills=["Python", "Docker"],
        )
        summary = format_profile_summary(p)
        assert "Python" in summary
        assert "Docker" in summary

    def test_includes_address(self) -> None:
        p = Profile(
            name="Bob",
            email="bob@example.com",
            address=Address(city="Montreal", province_state="QC"),
        )
        summary = format_profile_summary(p)
        assert "Montreal" in summary

    def test_includes_employment(self) -> None:
        p = Profile(
            name="Bob",
            email="bob@example.com",
            employment_history=[
                Employment(company="BigCo", title="Senior Engineer"),
            ],
        )
        summary = format_profile_summary(p)
        assert "BigCo" in summary
        assert "Senior Engineer" in summary

    def test_includes_education(self) -> None:
        p = Profile(
            name="Bob",
            email="bob@example.com",
            education=[
                Education(institution="MIT", degree="BSc", field="CS"),
            ],
        )
        summary = format_profile_summary(p)
        assert "MIT" in summary
        assert "BSc" in summary


# ---------------------------------------------------------------------------
# _group_questions tests
# ---------------------------------------------------------------------------

class TestGroupQuestions:
    def test_empty_report_returns_no_groups(self) -> None:
        report = GapReport(gaps=[])
        groups = _group_questions(report)
        assert groups == []

    def test_salary_gaps_grouped_together(self) -> None:
        report = GapReport(
            gaps=[
                Gap("aspirations.salary_minimum", "min salary", GapPriority.REQUIRED),
                Gap("aspirations.salary_target", "target salary", GapPriority.REQUIRED),
            ]
        )
        groups = _group_questions(report)
        assert len(groups) == 1
        assert groups[0][0] == "salary"
        assert "aspirations.salary_minimum" in groups[0][1]
        assert "aspirations.salary_target" in groups[0][1]

    def test_roles_and_arrangement_grouped(self) -> None:
        report = GapReport(
            gaps=[
                Gap("aspirations.target_roles", "roles", GapPriority.REQUIRED),
                Gap("aspirations.work_arrangement", "arrangement", GapPriority.REQUIRED),
                Gap("aspirations.geographic_preferences", "geo", GapPriority.REQUIRED),
            ]
        )
        groups = _group_questions(report)
        group_names = [g[0] for g in groups]
        assert "roles_and_arrangement" in group_names

    def test_multiple_groups_returned(self) -> None:
        report = GapReport(
            gaps=[
                Gap("skills", "skills", GapPriority.REQUIRED),
                Gap("aspirations.urgency", "urgency", GapPriority.REQUIRED),
                Gap("languages", "languages", GapPriority.NICE_TO_HAVE),
            ]
        )
        groups = _group_questions(report)
        group_names = [g[0] for g in groups]
        assert "skills" in group_names
        assert "urgency" in group_names
        assert "languages" in group_names


# ---------------------------------------------------------------------------
# build_profile integration tests
# ---------------------------------------------------------------------------

class TestBuildProfileWithCV:
    """Test the builder when the user provides a CV file."""

    async def test_with_cv_no_corrections(self, tmp_path: Path) -> None:
        """User provides a CV, accepts extraction, answers gap questions."""
        # Create a fake CV text file
        cv_file = tmp_path / "resume.txt"
        cv_file.write_text(
            "Jonathan Pelletier\njonathan@example.com\nPython, AWS",
            encoding="utf-8",
        )
        profile_path = tmp_path / "profile.yaml"

        # Script: CV path, no corrections, then answer gap questions
        # TestModel returns default Profile values; gap questions follow
        io = ScriptedIO([
            str(cv_file),     # CV path
            "no",             # no corrections
            # The TestModel will fill in defaults, so gap questions depend on
            # what TestModel produces. We provide generous answers for any gaps.
            "Applied AI Engineer, remote, Montreal and Remote",
            "minimum 90k, target 120k",
            "Very urgent",
            "Python, TypeScript, AWS, Docker",
            "English native, French fluent",
            "AWS Solutions Architect",
        ])

        result = await build_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=profile_path,
            _model_override=TestModel(),
        )

        assert isinstance(result, Profile)
        assert profile_path.exists()

    async def test_with_cv_and_corrections(self, tmp_path: Path) -> None:
        """User provides a CV and requests corrections."""
        cv_file = tmp_path / "resume.txt"
        cv_file.write_text(
            "Bob Smith\nbob@example.com\nJava, Spring",
            encoding="utf-8",
        )
        profile_path = tmp_path / "profile.yaml"

        io = ScriptedIO([
            str(cv_file),             # CV path
            "My name is actually Robert Smith",  # correction
            # Gap-filling answers
            "Staff Engineer, hybrid, Toronto",
            "min 100k, target 140k",
            "Within 3 months",
            "Java, Spring, Kubernetes",
            "English native",
            "none",
        ])

        result = await build_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=profile_path,
            _model_override=TestModel(),
        )

        assert isinstance(result, Profile)
        assert profile_path.exists()

    async def test_cv_not_found_falls_back(self, tmp_path: Path) -> None:
        """If the CV file doesn't exist, fall back to manual entry."""
        profile_path = tmp_path / "profile.yaml"

        io = ScriptedIO([
            "/nonexistent/resume.pdf",  # bad path
            "Alice Wonder",             # name
            "alice@example.com",        # email
            # Gap-filling answers
            "Data Scientist, remote, anywhere",
            "min 80k, target 110k",
            "Not urgent",
            "Python, R, SQL",
            "English fluent",
            "none",
        ])

        result = await build_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=profile_path,
            _model_override=TestModel(),
        )

        assert isinstance(result, Profile)
        assert profile_path.exists()


class TestBuildProfileNoCV:
    """Test the builder when the user skips CV."""

    async def test_no_cv_builds_from_scratch(self, tmp_path: Path) -> None:
        """User says 'no' to CV, builds profile from scratch."""
        profile_path = tmp_path / "profile.yaml"

        io = ScriptedIO([
            "no",                     # no CV
            "Charlie Brown",          # name
            "charlie@example.com",    # email
            # Gap-filling answers
            "Frontend Developer, on-site, New York",
            "min 70k, target 95k",
            "Somewhat urgent",
            "React, TypeScript, CSS",
            "English native",
            "skip",
        ])

        result = await build_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=profile_path,
            _model_override=TestModel(),
        )

        assert isinstance(result, Profile)
        assert profile_path.exists()
        # Verify we can load it back
        loaded = load_profile(profile_path)
        assert isinstance(loaded, Profile)


class TestBuildProfileIncremental:
    """Test incremental updates when a profile already exists."""

    async def test_existing_profile_loaded(self, tmp_path: Path) -> None:
        """When a profile exists, it should be loaded and presented."""
        profile_path = tmp_path / "profile.yaml"
        existing = Profile(
            name="Diana Prince",
            email="diana@example.com",
            skills=["Python", "Go"],
            aspirations=Aspirations(
                target_roles=["Backend Engineer"],
                salary_minimum=100000,
                salary_target=130000,
                urgency="within_3_months",
                geographic_preferences=["Remote"],
                work_arrangement=["remote"],
            ),
        )
        save_profile(existing, profile_path)

        # User skips CV, only answers nice-to-have gaps
        io = ScriptedIO([
            "no",                          # no CV
            # Only nice-to-have gaps remain: languages, certifications
            "English native, French fluent",
            "AWS SAA",
        ])

        result = await build_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=profile_path,
            _model_override=TestModel(),
        )

        assert isinstance(result, Profile)
        # The printed output should mention the existing profile
        printed_text = "\n".join(io.printed)
        assert "Diana Prince" in printed_text

    async def test_existing_profile_with_cv_update(self, tmp_path: Path) -> None:
        """Existing profile + new CV = merged result."""
        profile_path = tmp_path / "profile.yaml"
        existing = Profile(
            name="Eve Adams",
            email="eve@example.com",
            skills=["Python"],
        )
        save_profile(existing, profile_path)

        cv_file = tmp_path / "resume.txt"
        cv_file.write_text(
            "Eve Adams\neve@example.com\nPython, Rust, Docker",
            encoding="utf-8",
        )

        io = ScriptedIO([
            str(cv_file),     # CV path
            "no",             # no corrections
            # Gap-filling answers
            "ML Engineer, hybrid, San Francisco",
            "min 120k, target 160k",
            "Urgent",
            "Python, Rust, Docker, ML",
            "English native",
            "none",
        ])

        result = await build_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=profile_path,
            _model_override=TestModel(),
        )

        assert isinstance(result, Profile)
        assert profile_path.exists()


class TestBuildProfileOutput:
    """Test that the builder prints expected messages."""

    async def test_greeting_printed(self, tmp_path: Path) -> None:
        """The builder should print a welcome message."""
        profile_path = tmp_path / "profile.yaml"

        io = ScriptedIO([
            "no",
            "Test User",
            "test@example.com",
            "Engineer, remote, anywhere",
            "min 80k, target 100k",
            "Not urgent",
            "Python",
            "English",
            "none",
        ])

        await build_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=profile_path,
            _model_override=TestModel(),
        )

        printed_text = "\n".join(io.printed)
        assert "Welcome to emplaiyed" in printed_text

    async def test_save_confirmation_printed(self, tmp_path: Path) -> None:
        """The builder should confirm where the profile was saved."""
        profile_path = tmp_path / "profile.yaml"

        io = ScriptedIO([
            "no",
            "Test User",
            "test@example.com",
            "Engineer, remote, anywhere",
            "min 80k, target 100k",
            "Not urgent",
            "Python",
            "English",
            "none",
        ])

        await build_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=profile_path,
            _model_override=TestModel(),
        )

        printed_text = "\n".join(io.printed)
        assert "Profile saved to" in printed_text
        assert "emplaiyed profile show" in printed_text

    async def test_cv_parsing_message_printed(self, tmp_path: Path) -> None:
        """When a CV is provided, 'Parsing your CV' should appear."""
        cv_file = tmp_path / "resume.txt"
        cv_file.write_text("Jane Doe\njane@example.com", encoding="utf-8")
        profile_path = tmp_path / "profile.yaml"

        io = ScriptedIO([
            str(cv_file),
            "no",
            "Backend, remote, Montreal",
            "min 90k, target 120k",
            "Urgent",
            "Python, Go",
            "English, French",
            "none",
        ])

        await build_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=profile_path,
            _model_override=TestModel(),
        )

        printed_text = "\n".join(io.printed)
        assert "Parsing your CV" in printed_text
        assert "Here's what I extracted" in printed_text
