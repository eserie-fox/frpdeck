"""Sync command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._privilege import ensure_root_privileges
from frpdeck.domain.errors import ConfigLoadError, FrpdeckError, PermissionOperationError
from frpdeck.logging import instance_logging_context
from frpdeck.services.installer import analyze_sync_root_requirements, sync_rendered_to_runtime
from frpdeck.storage.file_lock import instance_lock
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("sync")
    def sync_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Mirror rendered/ into runtime/config without rendering, validating, or reloading."""
        instance_dir = instance.resolve()
        try:
            node = load_node_config(instance_dir)
            if ensure_root_privileges(
                operation="sync",
                reasons=analyze_sync_root_requirements(instance_dir, node),
                sudo_requested=sudo,
                command_args=["sync", "--instance", str(instance_dir)],
            ):
                return
            with instance_lock(instance_dir / "state" / ".frpdeck.lock"):
                with instance_logging_context(instance_dir, node=node):
                    config_path = sync_rendered_to_runtime(instance_dir, node)
        except typer.Exit:
            raise
        except PermissionOperationError as exc:
            typer.echo(f"ERROR: {exc}")
            raise typer.Exit(code=1) from exc
        except (ConfigLoadError, FrpdeckError) as exc:
            typer.echo(f"ERROR: sync failed: {exc}")
            raise typer.Exit(code=1) from exc

        typer.echo(f"runtime config synced: {config_path}")
