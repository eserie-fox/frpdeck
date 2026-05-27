"""Upgrade command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._download_progress import CliDownloadProgressReporter
from frpdeck.commands._invocation import build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges, unreadable_path_reason
from frpdeck.domain.errors import (
    CommandExecutionError,
    ConfigLoadError,
    ConfigValidationError,
    DownloadError,
    PermissionOperationError,
)
from frpdeck.logging.daily_symlink import instance_logging_context
from frpdeck.services.installer import analyze_upgrade_root_requirements, install_from_archive, install_from_release
from frpdeck.services.release_checker import get_release
from frpdeck.services.systemd_manager import restart_service
from frpdeck.storage.file_lock import instance_lock
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("upgrade")
    def upgrade_command(
        ctx: typer.Context,
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        archive: Path | None = typer.Option(None, "--archive", help="Offline frp tar.gz archive"),
        restart_after: bool = typer.Option(True, "--restart/--no-restart", help="Restart service after upgrade"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Upgrade the installed frp binary."""
        instance_dir = instance.resolve()
        resolved_archive = archive.resolve() if archive is not None else None
        invocation = build_command_invocation(
            ctx,
            overrides={
                "instance": instance_dir,
                "archive": resolved_archive,
            },
        )
        try:
            if maybe_reexec_with_sudo(
                operation="upgrade",
                sudo_requested=sudo,
                invocation=invocation,
            ):
                return
            preload_reasons: list[str] = []
            node_reason = unreadable_path_reason(instance_dir / "node.yaml", label="node config")
            if node_reason is not None:
                preload_reasons.append(node_reason)
            archive_reason = (
                unreadable_path_reason(resolved_archive, label="archive") if resolved_archive is not None else None
            )
            if archive_reason is not None:
                preload_reasons.append(archive_reason)
            raise_for_missing_privileges(
                operation="upgrade",
                reasons=preload_reasons,
                invocation=invocation,
            )
            node = load_node_config(instance_dir)
            raise_for_missing_privileges(
                operation="upgrade",
                reasons=analyze_upgrade_root_requirements(
                    instance_dir,
                    node,
                    archive=resolved_archive,
                    restart_after=restart_after,
                ),
                invocation=invocation,
            )
            with instance_lock(instance_dir / "state" / ".frpdeck.lock"):
                with instance_logging_context(instance_dir, node=node):
                    download_reporter = CliDownloadProgressReporter(typer.echo)
                    if resolved_archive is not None:
                        version = install_from_archive(instance_dir, node, resolved_archive, node.binary.version)
                    elif node.binary.local_archive is not None:
                        source = node.binary.local_archive
                        resolved = source if source.is_absolute() else (instance_dir / source).resolve()
                        version = install_from_archive(instance_dir, node, resolved, node.binary.version)
                    else:
                        release = get_release(node.binary)
                        version = install_from_release(
                            instance_dir,
                            node,
                            release,
                            progress=download_reporter.update,
                            download_started=download_reporter.start,
                            download_finished=download_reporter.finish,
                        )
                    if restart_after:
                        restart_service(node.service.service_name)
        except (
            CommandExecutionError,
            ConfigLoadError,
            ConfigValidationError,
            DownloadError,
            PermissionOperationError,
        ) as exc:
            typer.echo(f"ERROR: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo(f"upgraded to {version}")
