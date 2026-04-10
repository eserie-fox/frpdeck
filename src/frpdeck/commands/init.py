"""Init command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._invocation import build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges
from frpdeck.domain.errors import PermissionOperationError
from frpdeck.domain.enums import Role
from frpdeck.services.scaffold import analyze_init_root_requirements, scaffold_instance


def register(app: typer.Typer) -> None:
    @app.command("init")
    def init_command(
        ctx: typer.Context,
        role: Role,
        instance_name: str,
        directory: Path = typer.Option(Path("."), "--directory", help="Base directory for the new instance"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Create a new instance directory."""
        base_dir = directory.resolve()
        invocation = build_command_invocation(ctx, overrides={"directory": base_dir})
        try:
            if maybe_reexec_with_sudo(
                operation="init",
                sudo_requested=sudo,
                invocation=invocation,
                subject="the target directory",
            ):
                return
            raise_for_missing_privileges(
                operation="init",
                reasons=analyze_init_root_requirements(base_dir, instance_name),
                invocation=invocation,
                subject="the target directory",
            )
            instance_dir = scaffold_instance(base_dir, role, instance_name)
        except PermissionOperationError as exc:
            typer.echo(f"ERROR: {exc}")
            raise typer.Exit(code=1) from exc
        except OSError as exc:
            typer.echo(f"ERROR: init failed: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo(f"created instance: {instance_dir}")
