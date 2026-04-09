"""Render command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._invocation import build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges, unreadable_path_reason
from frpdeck.domain.errors import ConfigLoadError, PermissionOperationError
from frpdeck.domain.enums import Role
from frpdeck.logging.daily_symlink import instance_logging_context
from frpdeck.services.renderer import analyze_render_root_requirements, render_instance
from frpdeck.storage.load import load_node_config, load_proxy_file


def register(app: typer.Typer) -> None:
    @app.command("render")
    def render_command(
        ctx: typer.Context,
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Render FRP and systemd files into rendered/ only."""
        instance_dir = instance.resolve()
        invocation = build_command_invocation(ctx, overrides={"instance": instance_dir})
        node_config_path = instance_dir / "node.yaml"
        try:
            if maybe_reexec_with_sudo(
                operation="render",
                sudo_requested=sudo,
                invocation=invocation,
            ):
                return
            node_reason = unreadable_path_reason(node_config_path, label="node config")
            raise_for_missing_privileges(
                operation="render",
                reasons=[node_reason] if node_reason is not None else [],
                invocation=invocation,
            )
            node = load_node_config(instance_dir)
            preload_reasons: list[str] = []
            if node.role == Role.CLIENT:
                proxy_reason = unreadable_path_reason(instance_dir / "proxies.yaml", label="proxy config")
                if proxy_reason is not None:
                    preload_reasons.append(proxy_reason)
            preload_reasons.extend(analyze_render_root_requirements(instance_dir, node))
            raise_for_missing_privileges(
                operation="render",
                reasons=preload_reasons,
                invocation=invocation,
            )
            with instance_logging_context(instance_dir, node=node):
                proxies = load_proxy_file(instance_dir) if node.role == Role.CLIENT else None
                summary = render_instance(instance_dir, node, proxies)
        except PermissionOperationError as exc:
            typer.echo(f"ERROR: {exc}")
            raise typer.Exit(code=1) from exc
        except ConfigLoadError as exc:
            typer.echo(f"ERROR: render failed: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo(f"main config: {summary.main_config_path}")
        typer.echo(f"systemd unit: {summary.systemd_unit_path}")
        typer.echo(f"proxy includes: {len(summary.rendered_proxy_paths)}")
