"""Reload command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.domain.enums import Role
from frpdeck.domain.errors import CommandExecutionError
from frpdeck.domain.state import ClientNodeConfig
from frpdeck.services.runtime import run_command
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("reload")
    def reload_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    ) -> None:
        """Reload a client instance via frpc reload."""
        instance_dir = instance.resolve()
        node = load_node_config(instance_dir)
        if node.role != Role.CLIENT:
            typer.echo("ERROR: reload is only supported for client instances")
            raise typer.Exit(code=1)
        assert isinstance(node, ClientNodeConfig)
        if not node.client.web_server.addr or not node.client.web_server.port:
            typer.echo("ERROR: client.web_server.addr and client.web_server.port are required for reload")
            raise typer.Exit(code=1)
        paths = node.resolved_paths(instance_dir)
        if not paths.binary_path(node.role).exists():
            typer.echo(f"ERROR: frpc binary not found: {paths.binary_path(node.role)}; run apply or upgrade first")
            raise typer.Exit(code=1)
        if not paths.config_path(node.role).exists():
            typer.echo(f"ERROR: runtime config not found: {paths.config_path(node.role)}; run render/apply first")
            raise typer.Exit(code=1)
        try:
            result = run_command([str(paths.binary_path(node.role)), "reload", "-c", str(paths.config_path(node.role))])
        except CommandExecutionError as exc:
            typer.echo(f"ERROR: failed to reload client {node.instance_name}: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo(result.stdout or "reload completed")
