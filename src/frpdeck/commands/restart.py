"""Restart command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.domain.errors import CommandExecutionError
from frpdeck.services.systemd_manager import restart_service
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("restart")
    def restart_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    ) -> None:
        """Restart the systemd service for an instance."""
        node = load_node_config(instance.resolve())
        try:
            restart_service(node.service.service_name)
        except CommandExecutionError as exc:
            typer.echo(f"ERROR: failed to restart {node.service.service_name}: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo(f"restarted {node.service.service_name}")
