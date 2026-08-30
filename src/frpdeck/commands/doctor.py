"""Doctor command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.commands._help import MAINTENANCE_AND_DIAGNOSTICS
from frpdeck.commands.output import echo_error
from frpdeck.domain.errors import FrpdeckError
from frpdeck.logging.daily_symlink import instance_logging_context
from frpdeck.services.doctor import run_doctor
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("doctor", rich_help_panel=MAINTENANCE_AND_DIAGNOSTICS)
    def doctor_command(
        instance: Path | None = typer.Option(None, "--instance", help="Instance directory"),
        system_only: bool = typer.Option(False, "--system-only", help="Diagnose only the system environment"),
    ) -> None:
        """Diagnose the local environment and instance."""
        if system_only and instance is not None:
            raise typer.BadParameter("--instance cannot be combined with --system-only", param_hint="--instance")

        instance_dir = None if system_only else (instance or Path(".")).resolve()
        node = None
        config_error = None
        node_path = instance_dir / "node.yaml" if instance_dir is not None else None
        if node_path is not None and node_path.exists():
            try:
                node = load_node_config(instance_dir)
            except (FrpdeckError, OSError, UnicodeError) as exc:
                config_error = str(exc)

        if instance_dir is not None and node is not None:
            with instance_logging_context(instance_dir, node=node):
                checks = run_doctor(instance_dir, node, config_error=config_error)
        else:
            checks = run_doctor(instance_dir, node, config_error=config_error)
        failed = False
        for check in checks:
            status = "OK" if check.ok else "FAIL"
            typer.echo(f"[{status}] {check.name}: {check.detail}", err=not check.ok)
            if not check.ok:
                failed = True
        if failed:
            echo_error("doctor found issues that may block apply/restart/status in this environment")
            raise typer.Exit(code=1)
