"""Status command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._help import COMMON_WORKFLOW
from frpdeck.commands.output import echo_error, echo_warning, emit_json_envelope
from frpdeck.domain.errors import ConfigLoadError, FrpdeckError
from frpdeck.domain.status_models import InstanceStatus
from frpdeck.logging.daily_symlink import instance_logging_context
from frpdeck.services.status_service import StatusService
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("status", rich_help_panel=COMMON_WORKFLOW)
    def status_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    ) -> None:
        """Show instance and service status."""
        instance_dir = instance.resolve()
        try:
            try:
                node = load_node_config(instance_dir)
            except ConfigLoadError:
                node = None
            if node is None:
                summary = StatusService().get_instance_status(instance_dir)
            else:
                with instance_logging_context(
                    instance_dir,
                    node=node,
                    stream_override="none" if json_output else None,
                ):
                    summary = StatusService().get_instance_status(instance_dir)
        except (FrpdeckError, OSError, UnicodeError) as exc:
            summary = InstanceStatus(instance=str(instance_dir), errors=[f"status failed: {exc}"])
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
            echo_warning(warning)
        for error in summary.errors:
            echo_error(error)
        if summary.errors:
            raise typer.Exit(code=1)
