"""Render command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.domain.enums import Role
from frpdeck.services.renderer import render_instance
from frpdeck.storage.load import load_node_config, load_proxy_file


def register(app: typer.Typer) -> None:
    @app.command("render")
    def render_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    ) -> None:
        """Render FRP and systemd files into rendered/."""
        instance_dir = instance.resolve()
        node = load_node_config(instance_dir)
        proxies = load_proxy_file(instance_dir) if node.role == Role.CLIENT else None
        summary = render_instance(instance_dir, node, proxies)
        typer.echo(f"main config: {summary.main_config_path}")
        typer.echo(f"systemd unit: {summary.systemd_unit_path}")
        typer.echo(f"proxy includes: {len(summary.rendered_proxy_paths)}")
