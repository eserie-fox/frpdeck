"""Validate command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._help import PREFLIGHT_AND_ADVANCED_DEPLOYMENT
from frpdeck.commands.output import echo_error
from frpdeck.domain.enums import Role
from frpdeck.domain.errors import FrpdeckError
from frpdeck.logging.daily_symlink import instance_logging_context
from frpdeck.services.verifier import validate_instance
from frpdeck.storage.load import load_node_config, load_proxy_file


def register(app: typer.Typer) -> None:
    @app.command("validate", rich_help_panel=PREFLIGHT_AND_ADVANCED_DEPLOYMENT)
    def validate_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    ) -> None:
        """Validate source configuration without changing the system."""
        instance_dir = instance.resolve()
        try:
            node = load_node_config(instance_dir)
            with instance_logging_context(instance_dir, node=node):
                proxies = load_proxy_file(instance_dir) if node.role == Role.CLIENT else None
                errors = validate_instance(instance_dir, node, proxies)
        except (FrpdeckError, OSError, UnicodeError) as exc:
            echo_error(f"validate failed: {exc}")
            raise typer.Exit(code=1) from exc
        if errors:
            for error in errors:
                echo_error(error)
            raise typer.Exit(code=1)
        typer.echo("validation passed")
