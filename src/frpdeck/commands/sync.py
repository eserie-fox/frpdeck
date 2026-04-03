"""Sync command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._invocation import build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges, unreadable_path_reason
from frpdeck.domain.errors import ConfigLoadError, FrpdeckError, PermissionOperationError
from frpdeck.logging import instance_logging_context
from frpdeck.services.installer import analyze_sync_root_requirements, sync_rendered_to_runtime
from frpdeck.storage.file_lock import instance_lock
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("sync")
    def sync_command(
        ctx: typer.Context,
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Mirror rendered/ into runtime/config without rendering, validating, or reloading."""
        instance_dir = instance.resolve()
        invocation = build_command_invocation(ctx, overrides={"instance": instance_dir})
        try:
            if maybe_reexec_with_sudo(
                operation="sync",
                sudo_requested=sudo,
                invocation=invocation,
            ):
                return
            node_reason = unreadable_path_reason(instance_dir / "node.yaml", label="node config")
            raise_for_missing_privileges(
                operation="sync",
                reasons=[node_reason] if node_reason is not None else [],
                invocation=invocation,
            )
            node = load_node_config(instance_dir)
            raise_for_missing_privileges(
                operation="sync",
                reasons=analyze_sync_root_requirements(instance_dir, node),
                invocation=invocation,
            )
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
