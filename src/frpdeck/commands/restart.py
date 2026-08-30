"""Restart command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._help import RUNTIME_CONTROL
from frpdeck.commands._invocation import build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges, unreadable_path_reason
from frpdeck.commands.output import echo_error
from frpdeck.domain.errors import CommandExecutionError, ConfigLoadError, FrpdeckError, PermissionOperationError
from frpdeck.logging.daily_symlink import instance_logging_context
from frpdeck.services.systemd_manager import restart_service
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("restart", rich_help_panel=RUNTIME_CONTROL)
    def restart_command(
        ctx: typer.Context,
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Restart the instance's systemd service. Uses current runtime config; use apply for a complete deployment."""
        instance_dir = instance.resolve()
        invocation = build_command_invocation(ctx, overrides={"instance": instance_dir})
        try:
            if maybe_reexec_with_sudo(
                operation="restart",
                sudo_requested=sudo,
                invocation=invocation,
            ):
                return
            node_reason = unreadable_path_reason(instance_dir / "node.yaml", label="node config")
            raise_for_missing_privileges(
                operation="restart",
                reasons=[node_reason] if node_reason is not None else [],
                invocation=invocation,
            )
            node = load_node_config(instance_dir)
            raise_for_missing_privileges(
                operation="restart",
                reasons=["will manage system service via systemctl"],
                invocation=invocation,
            )
            with instance_logging_context(instance_dir, node=node):
                restart_service(node.service.service_name)
        except PermissionOperationError as exc:
            echo_error(str(exc))
            raise typer.Exit(code=1) from exc
        except ConfigLoadError as exc:
            echo_error(f"restart failed: {exc}")
            raise typer.Exit(code=1) from exc
        except CommandExecutionError as exc:
            echo_error(f"failed to restart {node.service.service_name}: {exc}")
            raise typer.Exit(code=1) from exc
        except FrpdeckError as exc:
            echo_error(f"restart failed: {exc}")
            raise typer.Exit(code=1) from exc
        except (OSError, UnicodeError) as exc:
            echo_error(f"restart failed: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo(f"restarted {node.service.service_name}")
