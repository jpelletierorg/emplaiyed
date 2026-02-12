"""Tests for the ``emplaiyed profile build`` CLI command.

These tests verify the CLI wiring — that the command exists, calls the
builder, and handles edge cases. The builder logic itself is tested
separately in test_builder.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from emplaiyed.core.models import Profile
from emplaiyed.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProfileBuildCommand:
    """Tests for the profile build CLI command."""

    def test_command_exists(self) -> None:
        """The 'profile build' command should be registered."""
        result = runner.invoke(app, ["profile", "build", "--help"])
        assert result.exit_code == 0
        assert "build" in result.output.lower()

    def test_build_calls_builder(self, tmp_path: Path) -> None:
        """The build command should call the builder module."""
        profile = Profile(name="CLI Test", email="cli@example.com")

        call_args: dict = {}

        async def mock_build(**kwargs):
            call_args.update(kwargs)
            return profile

        # The import happens inside profile_build(), so we patch at the
        # module source: emplaiyed.profile.builder.build_profile
        with patch(
            "emplaiyed.profile.builder.build_profile",
            side_effect=mock_build,
        ):
            result = runner.invoke(app, ["profile", "build"])

        # The builder should have been called with prompt_fn and print_fn
        assert "prompt_fn" in call_args
        assert "print_fn" in call_args

    def test_build_help_text(self) -> None:
        """The build command should have a help string."""
        result = runner.invoke(app, ["profile", "build", "--help"])
        assert result.exit_code == 0
        # Help text should mention "build" or "profile"
        assert "build" in result.output.lower() or "profile" in result.output.lower()

    def test_profile_subcommands_listed(self) -> None:
        """'emplaiyed profile' should list build as a subcommand."""
        result = runner.invoke(app, ["profile", "--help"])
        assert result.exit_code == 0
        assert "build" in result.output
        assert "show" in result.output
        assert "path" in result.output


class TestProfileBuildEdgeCases:
    """Edge-case tests for the profile build CLI command."""

    def test_keyboard_interrupt_handled(self) -> None:
        """KeyboardInterrupt during build should exit gracefully."""

        async def mock_build(**kwargs):
            raise KeyboardInterrupt()

        with patch(
            "emplaiyed.profile.builder.build_profile",
            side_effect=mock_build,
        ):
            result = runner.invoke(app, ["profile", "build"])

        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()
