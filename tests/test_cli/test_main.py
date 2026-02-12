from typer.testing import CliRunner

from emplaiyed.main import app

runner = CliRunner()


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "emplaiyed 0.1.0" in result.output


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert "AI-powered job seeking toolkit" in result.output


def test_debug_flag():
    """--debug flag should be accepted and not error."""
    result = runner.invoke(app, ["--debug", "sources", "list"])
    assert result.exit_code == 0
