"""Uninstall command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._invocation import build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges, unreadable_path_reason
from frpdeck.domain.errors import CommandExecutionError, ConfigLoadError, ConfigValidationError, PermissionOperationError
from frpdeck.logging import instance_logging_context
from frpdeck.services.uninstall import UninstallReport, analyze_uninstall_root_requirements, uninstall_instance
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("uninstall")
    def uninstall_command(
        ctx: typer.Context,
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        purge: bool = typer.Option(False, "--purge", help="Delete the entire instance directory after uninstall"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Remove installed artifacts for an instance."""
        instance_dir = instance.resolve()
        invocation = build_command_invocation(ctx, overrides={"instance": instance_dir})
        try:
            if maybe_reexec_with_sudo(
                operation="uninstall",
                sudo_requested=sudo,
                invocation=invocation,
            ):
                return
            node_reason = unreadable_path_reason(instance_dir / "node.yaml", label="node config")
            raise_for_missing_privileges(
                operation="uninstall",
                reasons=[node_reason] if node_reason is not None else [],
                invocation=invocation,
            )
            node = load_node_config(instance_dir)
            raise_for_missing_privileges(
                operation="uninstall",
                reasons=analyze_uninstall_root_requirements(instance_dir, purge=purge, node=node),
                invocation=invocation,
            )
            with instance_logging_context(instance_dir, node=node):
                report = uninstall_instance(instance_dir, purge=purge)
        except PermissionOperationError as exc:
            typer.echo(f"ERROR: {exc}")
            raise typer.Exit(code=1) from exc
        except (ConfigLoadError, ConfigValidationError, CommandExecutionError) as exc:
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
