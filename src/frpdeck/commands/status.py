"""Status command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.services.status import collect_status
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("status")
    def status_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    ) -> None:
        """Show instance and service status."""
        instance_dir = instance.resolve()
        node = load_node_config(instance_dir)
        try:
            summary = collect_status(instance_dir, node)
        except Exception as exc:
            typer.echo(f"ERROR: failed to collect status for {node.instance_name}: {exc}")
            raise typer.Exit(code=1) from exc
        for key, value in summary.items():
            typer.echo(f"{key}: {value}")
