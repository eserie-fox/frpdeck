"""Init command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.domain.enums import Role
from frpdeck.services.scaffold import scaffold_instance


def register(app: typer.Typer) -> None:
    @app.command("init")
    def init_command(
        role: Role,
        instance_name: str,
        directory: Path = typer.Option(Path("."), "--directory", help="Base directory for the new instance"),
    ) -> None:
        """Create a new instance directory."""
        instance_dir = scaffold_instance(directory.resolve(), role, instance_name)
        typer.echo(f"created instance: {instance_dir}")
