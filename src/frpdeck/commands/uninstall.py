"""Uninstall command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.domain.errors import CommandExecutionError, ConfigLoadError, ConfigValidationError, PermissionOperationError
from frpdeck.services.uninstall import UninstallReport, uninstall_instance


def register(app: typer.Typer) -> None:
    @app.command("uninstall")
    def uninstall_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        purge: bool = typer.Option(False, "--purge", help="Delete the entire instance directory after uninstall"),
    ) -> None:
        """Remove installed artifacts for an instance."""
        instance_dir = instance.resolve()
        try:
            report = uninstall_instance(instance_dir, purge=purge)
        except (ConfigLoadError, ConfigValidationError, PermissionOperationError, CommandExecutionError) as exc:
            typer.echo(f"ERROR: uninstall failed: {exc}")
            raise typer.Exit(code=1) from exc
        _emit_report(instance_dir, purge, report)


def _emit_report(instance_dir: Path, purge: bool, report: UninstallReport) -> None:
    if report.service_stopped:
        typer.echo(f"Stopped service: {report.service_name}")
    else:
        typer.echo(f"Service stop skipped or not needed: {report.service_name}")

    if report.service_disabled:
        typer.echo(f"Disabled service: {report.service_name}")
    else:
        typer.echo(f"Service disable skipped or not needed: {report.service_name}")

    if report.unit_removed:
        typer.echo(f"Removed unit file: {report.unit_path}")
    else:
        typer.echo(f"Unit file already absent: {report.unit_path}")

    if report.removed_paths:
        typer.echo("Removed paths:")
        for path in report.removed_paths:
            typer.echo(f"- {path}")

    if purge:
        typer.echo(f"Purged instance directory: {instance_dir}")
    else:
        if report.kept_paths:
            typer.echo("Kept paths:")
            for path in report.kept_paths:
                typer.echo(f"- {path}")
        typer.echo("System installation artifacts have been removed.")
        typer.echo(f"Instance configuration is still present in {instance_dir}.")
        typer.echo(f"If you no longer need it, you can remove it manually with: rm -rf {instance_dir}")

    for warning in report.warnings:
        typer.echo(f"WARNING: {warning}")