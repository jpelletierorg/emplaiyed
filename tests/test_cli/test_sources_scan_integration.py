"""Integration tests for `sources scan` — exercises the full flow through the CLI.

These tests exist specifically to catch bugs like the "closed database" issue
where DB operations happened after conn.close(). They mock only the external
boundaries (scraper, LLM) and let everything else run for real against a test DB.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from emplaiyed.core.database import init_db, list_applications, save_opportunity
from emplaiyed.core.models import (
    ApplicationStatus,
    Aspirations,
    Opportunity,
    Profile,
    ScoredOpportunity,
)
from emplaiyed.main import app

runner = CliRunner()


def _fake_profile() -> Profile:
    return Profile(
        name="Test User",
        email="test@example.com",
        skills=["Python", "AWS", "Docker"],
        aspirations=Aspirations(
            target_roles=["Backend Developer"],
            geographic_preferences=["Montreal"],
            work_arrangement=["remote"],
        ),
    )


def _fake_opportunities() -> list[Opportunity]:
    return [
        Opportunity(
            id=f"opp-{i}",
            source="fake",
            company=f"Company{i}",
            title=f"Role {i}",
            description=f"Description for role {i}",
            location="Montreal",
            scraped_at=datetime.now(),
        )
        for i in range(3)
    ]


def _fake_scored(opportunities: list[Opportunity]) -> list[ScoredOpportunity]:
    return [
        ScoredOpportunity(opportunity=opp, score=90 - i * 10, justification="Good fit")
        for i, opp in enumerate(opportunities)
    ]


def _make_persisting_source(opps: list[Opportunity]) -> MagicMock:
    """Create a fake source whose scrape_and_persist saves opportunities to DB."""
    async def _persist(query, db_conn):
        for opp in opps:
            save_opportunity(db_conn, opp)
        return opps

    source = MagicMock()
    source.name = "fake"
    source.scrape_and_persist = AsyncMock(side_effect=_persist)
    return source


class TestSourcesScanIntegration:
    """Full-flow integration tests using a real DB and mocked scraper/LLM."""

    def test_scan_with_scoring_uses_db_correctly(self, tmp_path: Path):
        """The scan→score flow must not close the DB before scoring finishes.

        This test would have caught the 'Cannot operate on a closed database' bug.
        The key: score_opportunities receives db_conn and uses it — if the conn
        was closed before this call, the mock's side_effect would raise.
        """
        db_path = tmp_path / "test.db"
        init_db(db_path).close()

        opps = _fake_opportunities()
        scored = _fake_scored(opps)

        async def _score_and_verify(profile, opportunities, *, db_conn=None, _model_override=None):
            """Mock that verifies the DB connection is still usable."""
            if db_conn is not None:
                # This would raise ProgrammingError if the connection was closed
                db_conn.execute("SELECT 1")
            return scored

        with (
            patch("emplaiyed.cli.sources_cmd.get_default_db_path", return_value=db_path),
            patch("emplaiyed.cli.sources_cmd.get_available_sources", return_value={"fake": _make_persisting_source(opps)}),
            patch("emplaiyed.cli.sources_cmd.try_load_profile", return_value=_fake_profile()),
            patch("emplaiyed.scoring.score_opportunities", new_callable=AsyncMock, side_effect=_score_and_verify),
            patch("emplaiyed.cli.sources_cmd._eager_generate_assets", return_value=0),
        ):
            result = runner.invoke(
                app, ["sources", "scan", "--source", "fake", "--keywords", "python"]
            )

        assert result.exit_code == 0, f"CLI failed:\n{result.output}"
        assert "3 new opportunities found" in result.output
        assert "scored" in result.output.lower()

    def test_scan_with_scoring_and_assets(self, tmp_path: Path):
        """Full flow: scan → score → asset generation. DB stays open throughout."""
        db_path = tmp_path / "test.db"
        init_db(db_path).close()

        opps = _fake_opportunities()
        scored = _fake_scored(opps)

        with (
            patch("emplaiyed.cli.sources_cmd.get_default_db_path", return_value=db_path),
            patch("emplaiyed.cli.sources_cmd.get_available_sources", return_value={"fake": _make_persisting_source(opps)}),
            patch("emplaiyed.cli.sources_cmd.try_load_profile", return_value=_fake_profile()),
            patch("emplaiyed.scoring.score_opportunities", new_callable=AsyncMock, return_value=scored),
            patch("emplaiyed.generation.pipeline.generate_assets_batch", new_callable=AsyncMock, return_value=["path1", "path2", "path3"]),
        ):
            result = runner.invoke(
                app, ["sources", "scan", "--source", "fake", "--keywords", "python"]
            )

        assert result.exit_code == 0, f"CLI failed:\n{result.output}"
        assert "3 new opportunities found" in result.output

    def test_scan_without_profile_skips_scoring(self, tmp_path: Path):
        """When no profile exists, scoring is skipped and no DB errors occur."""
        db_path = tmp_path / "test.db"
        init_db(db_path).close()

        opps = _fake_opportunities()

        with (
            patch("emplaiyed.cli.sources_cmd.get_default_db_path", return_value=db_path),
            patch("emplaiyed.cli.sources_cmd.get_available_sources", return_value={"fake": _make_persisting_source(opps)}),
            patch("emplaiyed.cli.sources_cmd.try_load_profile", return_value=None),
        ):
            result = runner.invoke(
                app, ["sources", "scan", "--source", "fake", "--keywords", "python"]
            )

        assert result.exit_code == 0, f"CLI failed:\n{result.output}"
        assert "3 new opportunities found" in result.output
        assert "skipping scoring" in result.output.lower()

    def test_scan_scoring_failure_doesnt_crash(self, tmp_path: Path):
        """If scoring raises an exception, the scan still completes gracefully."""
        db_path = tmp_path / "test.db"
        init_db(db_path).close()

        opps = _fake_opportunities()

        with (
            patch("emplaiyed.cli.sources_cmd.get_default_db_path", return_value=db_path),
            patch("emplaiyed.cli.sources_cmd.get_available_sources", return_value={"fake": _make_persisting_source(opps)}),
            patch("emplaiyed.cli.sources_cmd.try_load_profile", return_value=_fake_profile()),
            patch("emplaiyed.scoring.score_opportunities", new_callable=AsyncMock, side_effect=RuntimeError("LLM down")),
        ):
            result = runner.invoke(
                app, ["sources", "scan", "--source", "fake", "--keywords", "python"]
            )

        assert result.exit_code == 0, f"CLI failed:\n{result.output}"
        assert "Scoring failed" in result.output

    def test_scan_no_results(self, tmp_path: Path):
        """When scraper returns nothing, DB is handled correctly."""
        db_path = tmp_path / "test.db"
        init_db(db_path).close()

        fake_source = MagicMock()
        fake_source.name = "fake"
        fake_source.scrape_and_persist = AsyncMock(return_value=[])

        with (
            patch("emplaiyed.cli.sources_cmd.get_default_db_path", return_value=db_path),
            patch("emplaiyed.cli.sources_cmd.get_available_sources", return_value={"fake": fake_source}),
            patch("emplaiyed.cli.sources_cmd.try_load_profile", return_value=_fake_profile()),
        ):
            result = runner.invoke(
                app, ["sources", "scan", "--source", "fake", "--keywords", "python"]
            )

        assert result.exit_code == 0
        assert "No new opportunities found" in result.output
