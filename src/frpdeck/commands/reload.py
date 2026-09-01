"""Reload command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._help import RUNTIME_CONTROL
from frpdeck.commands._invocation import build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges, unreadable_path_reason
from frpdeck.commands.output import echo_error
from frpdeck.domain.enums import Role
from frpdeck.domain.errors import CommandExecutionError, ConfigLoadError, FrpdeckError, PermissionOperationError
from frpdeck.domain.state import ClientNodeConfig
from frpdeck.logging.daily_symlink import instance_logging_context
from frpdeck.services.installer import analyze_reload_root_requirements
from frpdeck.services.runtime import run_command
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("reload", rich_help_panel=RUNTIME_CONTROL)
    def reload_command(
        ctx: typer.Context,
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Reload client configuration without restarting the service. Client-only via the frpc control/web endpoint using current runtime/config."""
        instance_dir = instance.resolve()
        invocation = build_command_invocation(ctx, overrides={"instance": instance_dir})
        try:
            if maybe_reexec_with_sudo(
                operation="reload",
                sudo_requested=sudo,
                invocation=invocation,
            ):
                return
            node_reason = unreadable_path_reason(instance_dir / "node.yaml", label="node config")
            raise_for_missing_privileges(
                operation="reload",
                reasons=[node_reason] if node_reason is not None else [],
                invocation=invocation,
            )
            node = load_node_config(instance_dir)
            if node.role != Role.CLIENT:
                echo_error("reload is only supported for client instances")
                raise typer.Exit(code=1)
            assert isinstance(node, ClientNodeConfig)
            web_server = node.client.web_server
            if not web_server.enable:
                echo_error("client.web_server.enable must be true for reload because frpc reload requires webServer")
                raise typer.Exit(code=1)
            if not web_server.addr or not web_server.port:
                echo_error("client.web_server.addr and client.web_server.port are required for reload")
                raise typer.Exit(code=1)
            raise_for_missing_privileges(
                operation="reload",
                reasons=analyze_reload_root_requirements(instance_dir, node),
                invocation=invocation,
            )
            paths = node.resolved_paths(instance_dir)
            if not paths.binary_path(node.role).exists():
                echo_error(f"frpc binary not found: {paths.binary_path(node.role)}; run apply or upgrade first")
                raise typer.Exit(code=1)
            if not paths.config_path(node.role).exists():
                echo_error(f"FRP runtime config not found: {paths.config_path(node.role)}; run sync or apply first")
                raise typer.Exit(code=1)
            with instance_logging_context(instance_dir, node=node):
                result = run_command(
                    [str(paths.binary_path(node.role)), "reload", "-c", str(paths.config_path(node.role))]
                )
        except PermissionOperationError as exc:
            echo_error(str(exc))
            raise typer.Exit(code=1) from exc
        except ConfigLoadError as exc:
            echo_error(f"reload failed: {exc}")
            raise typer.Exit(code=1) from exc
        except CommandExecutionError as exc:
            echo_error(f"failed to reload client {node.instance_name}: {exc}")
            raise typer.Exit(code=1) from exc
        except FrpdeckError as exc:
            echo_error(f"reload failed: {exc}")
            raise typer.Exit(code=1) from exc
        except (OSError, UnicodeError) as exc:
            echo_error(f"reload failed: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo(result.stdout or "reload completed")
