from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from emplaiyed.core.models import Aspirations, Profile
from emplaiyed.main import app

runner = CliRunner()


def _mock_profile(**overrides) -> Profile:
    """Build a Profile with sensible defaults for testing."""
    defaults = dict(
        name="Test User",
        email="test@example.com",
        skills=["Python", "AWS", "Docker", "Kubernetes", "SQL"],
        aspirations=Aspirations(
            target_roles=["Software Engineer", "DevOps Engineer"],
            geographic_preferences=["Remote", "Longueuil"],
            work_arrangement=["remote", "hybrid"],
        ),
    )
    defaults.update(overrides)
    return Profile(**defaults)


class TestSourcesList:
    def test_list_shows_sources(self):
        result = runner.invoke(app, ["sources", "list"])
        assert result.exit_code == 0
        assert "manual" in result.output
        assert "emploi_quebec" in result.output

    def test_list_shows_status(self):
        result = runner.invoke(app, ["sources", "list"])
        assert result.exit_code == 0
        # manual should be ready, emploi_quebec should be stub
        assert "ready" in result.output
        assert "stub" in result.output or "not implemented" in result.output


class TestSourcesScan:
    def test_scan_unknown_source(self):
        result = runner.invoke(
            app, ["sources", "scan", "--source", "nonexistent", "--keywords", "python"]
        )
        assert result.exit_code == 1
        assert "Unknown source" in result.output

    def test_scan_manual_returns_no_results(self):
        """Manual source's scrape() returns empty, so scan should say no results."""
        result = runner.invoke(
            app, ["sources", "scan", "--source", "manual", "--keywords", "python"]
        )
        assert result.exit_code == 0
        assert "No new opportunities found" in result.output

    def test_scan_emploi_quebec_shows_not_implemented(self):
        result = runner.invoke(
            app,
            ["sources", "scan", "--source", "emploi_quebec", "--keywords", "python"],
        )
        assert result.exit_code == 1
        assert "not yet implemented" in result.output

    def test_scan_with_location(self):
        result = runner.invoke(
            app,
            [
                "sources",
                "scan",
                "--source",
                "manual",
                "--keywords",
                "python,ai",
                "--location",
                "Quebec City",
            ],
        )
        assert result.exit_code == 0

    def test_sources_no_args_shows_help(self):
        result = runner.invoke(app, ["sources"])
        assert "sources" in result.output.lower()


class TestScanProfileDerived:
    """Tests for keyword/location derivation from profile."""

    def test_derives_keywords_from_profile(self):
        """When --keywords omitted, derive from profile aspirations + skills."""
        profile = _mock_profile()
        with patch("emplaiyed.cli.sources_cmd.get_default_profile_path") as mock_path, \
             patch("emplaiyed.cli.sources_cmd.load_profile", return_value=profile):
            mock_path.return_value.exists.return_value = True
            result = runner.invoke(
                app, ["sources", "scan", "--source", "manual"]
            )
        assert result.exit_code == 0
        assert "Derived keywords from profile" in result.output

    def test_derives_location_from_profile(self):
        """When --location omitted, derive from geographic_preferences (skip Remote)."""
        profile = _mock_profile()
        with patch("emplaiyed.cli.sources_cmd.get_default_profile_path") as mock_path, \
             patch("emplaiyed.cli.sources_cmd.load_profile", return_value=profile):
            mock_path.return_value.exists.return_value = True
            result = runner.invoke(
                app, ["sources", "scan", "--source", "manual"]
            )
        assert result.exit_code == 0
        # Should pick "Longueuil" (first non-Remote preference)
        assert "Longueuil" in result.output

    def test_error_when_no_keywords_and_no_profile(self):
        """Error with helpful message when no keywords and no profile exists."""
        with patch("emplaiyed.cli.sources_cmd.get_default_profile_path") as mock_path:
            mock_path.return_value.exists.return_value = False
            result = runner.invoke(
                app, ["sources", "scan", "--source", "manual"]
            )
        assert result.exit_code == 1
        assert "No keywords provided" in result.output

    def test_explicit_keywords_skips_profile(self):
        """When --keywords is provided, profile should not be loaded for keywords."""
        result = runner.invoke(
            app,
            ["sources", "scan", "--source", "manual", "--keywords", "python"],
        )
        assert result.exit_code == 0
        assert "Derived keywords from profile" not in result.output

    def test_explicit_location_overrides_profile(self):
        """When --location is provided, it should be used as-is."""
        profile = _mock_profile()
        with patch("emplaiyed.cli.sources_cmd.get_default_profile_path") as mock_path, \
             patch("emplaiyed.cli.sources_cmd.load_profile", return_value=profile):
            mock_path.return_value.exists.return_value = True
            result = runner.invoke(
                app,
                ["sources", "scan", "--source", "manual", "--location", "Toronto"],
            )
        assert result.exit_code == 0
        assert "Toronto" in result.output
