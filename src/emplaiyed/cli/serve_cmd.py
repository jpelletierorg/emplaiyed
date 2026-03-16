"""CLI command to launch the web server."""

from __future__ import annotations

import typer


def serve_command(
    host: str = typer.Option("127.0.0.1", help="Bind address."),
    port: int = typer.Option(8420, help="Port to listen on."),
    reload: bool = typer.Option(False, help="Enable auto-reload for development."),
) -> None:
    """Launch the emplaiyed web interface."""
    import uvicorn

    typer.echo(f"Starting emplaiyed web UI at http://{host}:{port}")
    uvicorn.run(
        "emplaiyed.api.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )
