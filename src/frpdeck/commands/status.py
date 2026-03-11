"""Status command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands.output import emit_json_envelope
from frpdeck.services.status_service import StatusService


def register(app: typer.Typer) -> None:
    @app.command("status")
    def status_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    ) -> None:
        """Show instance and service status."""
        instance_dir = instance.resolve()
        summary = StatusService().get_instance_status(instance_dir)
        if json_output:
            emit_json_envelope(
                command="status",
                instance=instance_dir,
                ok=not summary.errors,
                data=summary,
                errors=summary.errors,
                warnings=summary.warnings,
            )
            if summary.errors:
                raise typer.Exit(code=1)
            return
        typer.echo(f"instance_name: {summary.instance_name}")
        typer.echo(f"role: {summary.role}")
        typer.echo(f"service_name: {summary.service_name}")
        typer.echo(f"current_version: {summary.current_version}")
        typer.echo(f"proxy_total: {summary.proxy_counts.total}")
        typer.echo(f"enabled_proxies: {summary.proxy_counts.enabled}")
        typer.echo(f"rendered_proxy_count: {summary.render_summary.rendered_proxy_count}")
        typer.echo(f"service_available: {summary.service_status.available}")
        if summary.service_status.active is not None:
            typer.echo(f"service_active: {summary.service_status.active}")
        if summary.client_runtime_status is not None:
            typer.echo(f"client_runtime_available: {summary.client_runtime_status.available}")
        for warning in summary.warnings:
            typer.echo(f"WARNING: {warning}")
        for error in summary.errors:
            typer.echo(f"ERROR: {error}")
        if summary.errors:
            raise typer.Exit(code=1)
