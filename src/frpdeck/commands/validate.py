"""Validate command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.domain.enums import Role
from frpdeck.domain.errors import ConfigValidationError
from frpdeck.services.verifier import validate_instance
from frpdeck.storage.load import load_node_config, load_proxy_file


def register(app: typer.Typer) -> None:
    @app.command("validate")
    def validate_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    ) -> None:
        """Validate source configuration."""
        instance_dir = instance.resolve()
        node = load_node_config(instance_dir)
        proxies = load_proxy_file(instance_dir) if node.role == Role.CLIENT else None
        errors = validate_instance(instance_dir, node, proxies)
        if errors:
            for error in errors:
                typer.echo(f"ERROR: {error}")
            raise typer.Exit(code=1)
        typer.echo("validation passed")
