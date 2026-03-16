"""Tests for the interactive profile enricher."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from pydantic_ai.models.test import TestModel

from emplaiyed.core.models import Employment, Profile
from emplaiyed.core.profile_store import load_profile, save_profile
from emplaiyed.profile.enricher import enrich_profile


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


def _save_profile_with_weak_highlights(path: Path) -> Profile:
    """Create and save a profile with duty-focused highlights."""
    profile = Profile(
        name="Test User",
        email="test@example.com",
        employment_history=[
            Employment(
                company="Acme Corp",
                title="Senior Engineer",
                highlights=[
                    "Manage a team of developers",
                    "Responsible for cloud infrastructure",
                ],
            ),
        ],
    )
    save_profile(profile, path)
    return profile


def _save_profile_with_strong_highlights(path: Path) -> Profile:
    """Create and save a profile with achievement-focused highlights."""
    profile = Profile(
        name="Test User",
        email="test@example.com",
        employment_history=[
            Employment(
                company="Acme Corp",
                title="Senior Engineer",
                highlights=[
                    "Reduced deployment time by 60%",
                    "Saved $200,000 annually",
                ],
            ),
        ],
    )
    save_profile(profile, path)
    return profile


class TestEnrichProfile:
    async def test_no_profile_raises(self, tmp_path: Path):
        io = ScriptedIO([])
        with pytest.raises(FileNotFoundError):
            await enrich_profile(
                prompt_fn=io.prompt,
                print_fn=io.display,
                profile_path=tmp_path / "nonexistent.yaml",
            )

    async def test_strong_highlights_no_questions(self, tmp_path: Path):
        """If all highlights are strong, no follow-up questions are asked."""
        path = tmp_path / "profile.yaml"
        _save_profile_with_strong_highlights(path)

        io = ScriptedIO([])  # No responses needed
        result = await enrich_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=path,
            _model_override=TestModel(),
        )

        assert isinstance(result, Profile)
        printed = "\n".join(io.printed)
        assert "look good" in printed

    async def test_weak_highlights_asks_questions(self, tmp_path: Path):
        """Duty-focused highlights trigger follow-up questions."""
        path = tmp_path / "profile.yaml"
        _save_profile_with_weak_highlights(path)

        io = ScriptedIO([
            "Team of 8, reduced deploy time from 2h to 30min",  # context
            "yes",  # accept rewrites
        ])

        result = await enrich_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=path,
            _model_override=TestModel(),
        )

        assert isinstance(result, Profile)
        printed = "\n".join(io.printed)
        assert "Acme Corp" in printed
        assert "duty-focused" in printed

    async def test_skip_role(self, tmp_path: Path):
        """User can skip a role's enrichment."""
        path = tmp_path / "profile.yaml"
        original = _save_profile_with_weak_highlights(path)

        io = ScriptedIO([
            "skip",  # skip this role
        ])

        result = await enrich_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=path,
            _model_override=TestModel(),
        )

        # Highlights should remain unchanged
        assert result.employment_history[0].highlights == original.employment_history[0].highlights

    async def test_decline_rewrites(self, tmp_path: Path):
        """User can decline the rewritten highlights."""
        path = tmp_path / "profile.yaml"
        original = _save_profile_with_weak_highlights(path)

        io = ScriptedIO([
            "Team of 5 engineers",  # context
            "no",  # reject rewrites
        ])

        result = await enrich_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=path,
            _model_override=TestModel(),
        )

        # Highlights should remain unchanged
        assert result.employment_history[0].highlights == original.employment_history[0].highlights

    async def test_profile_saved_after_enrichment(self, tmp_path: Path):
        """Profile is saved to disk after enrichment."""
        path = tmp_path / "profile.yaml"
        _save_profile_with_weak_highlights(path)

        io = ScriptedIO([
            "Team of 8, deployed to 3 regions",
            "yes",
        ])

        await enrich_profile(
            prompt_fn=io.prompt,
            print_fn=io.display,
            profile_path=path,
            _model_override=TestModel(),
        )

        # Verify profile was saved by reloading
        reloaded = load_profile(path)
        assert isinstance(reloaded, Profile)
