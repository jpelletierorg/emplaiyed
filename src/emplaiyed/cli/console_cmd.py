"""CLI command to launch the interactive work console."""

from __future__ import annotations


def console_command():
    """Launch the interactive work console."""
    from emplaiyed.console.app import WorkConsoleApp

    app = WorkConsoleApp()
    app.run()
