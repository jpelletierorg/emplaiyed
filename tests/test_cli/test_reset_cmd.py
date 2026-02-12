"""Tests for the reset command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from emplaiyed.core.database import init_db
from emplaiyed.main import app

runner = CliRunner()


class TestReset:
    def test_reset_deletes_db_and_assets(self, tmp_path: Path):
        db_path = tmp_path / "data" / "emplaiyed.db"
        assets_dir = tmp_path / "data" / "assets"

        # Create DB and some assets
        db_path.parent.mkdir(parents=True, exist_ok=True)
        init_db(db_path).close()
        asset_subdir = assets_dir / "app-123"
        asset_subdir.mkdir(parents=True)
        (asset_subdir / "cv.pdf").write_text("fake")

        assert db_path.exists()
        assert assets_dir.exists()

        with (
            patch("emplaiyed.cli.reset_cmd.get_default_db_path", return_value=db_path),
            patch("emplaiyed.cli.reset_cmd.find_project_root", return_value=tmp_path),
        ):
            result = runner.invoke(app, ["reset", "--force"])

        assert result.exit_code == 0
        assert "Deleted" in result.output
        assert not db_path.exists()
        assert not assets_dir.exists()

    def test_reset_nothing_to_delete(self, tmp_path: Path):
        db_path = tmp_path / "data" / "emplaiyed.db"

        with (
            patch("emplaiyed.cli.reset_cmd.get_default_db_path", return_value=db_path),
            patch("emplaiyed.cli.reset_cmd.find_project_root", return_value=tmp_path),
        ):
            result = runner.invoke(app, ["reset", "--force"])

        assert result.exit_code == 0
        assert "clean" in result.output.lower()

    def test_reset_prompts_without_force(self, tmp_path: Path):
        db_path = tmp_path / "data" / "emplaiyed.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        init_db(db_path).close()

        with (
            patch("emplaiyed.cli.reset_cmd.get_default_db_path", return_value=db_path),
            patch("emplaiyed.cli.reset_cmd.find_project_root", return_value=tmp_path),
        ):
            # Answer "n" to confirmation
            result = runner.invoke(app, ["reset"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output
        assert db_path.exists()  # Not deleted
