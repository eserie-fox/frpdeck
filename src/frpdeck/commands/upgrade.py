"""Upgrade command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.domain.errors import CommandExecutionError, ConfigValidationError, DownloadError, PermissionOperationError
from frpdeck.services.installer import install_from_archive, install_from_release
from frpdeck.services.release_checker import get_release
from frpdeck.services.systemd_manager import restart_service
from frpdeck.storage.file_lock import instance_lock
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("upgrade")
    def upgrade_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        archive: Path | None = typer.Option(None, "--archive", help="Offline frp tar.gz archive"),
        restart_after: bool = typer.Option(True, "--restart/--no-restart", help="Restart service after upgrade"),
    ) -> None:
        """Upgrade the installed frp binary."""
        instance_dir = instance.resolve()
        with instance_lock(instance_dir / "state" / ".frpdeck.lock"):
            node = load_node_config(instance_dir)
            try:
                if archive is not None:
                    version = install_from_archive(instance_dir, node, archive.resolve(), node.binary.version)
                elif node.binary.local_archive is not None:
                    source = node.binary.local_archive
                    resolved = source if source.is_absolute() else (instance_dir / source).resolve()
                    version = install_from_archive(instance_dir, node, resolved, node.binary.version)
                else:
                    release = get_release(node.binary)
                    version = install_from_release(instance_dir, node, release)
                if restart_after:
                    restart_service(node.service.service_name)
            except (CommandExecutionError, ConfigValidationError, DownloadError, PermissionOperationError) as exc:
                typer.echo(f"ERROR: {exc}")
                raise typer.Exit(code=1) from exc
        typer.echo(f"upgraded to {version}")
