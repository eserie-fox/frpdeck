"""Doctor command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.services.doctor import run_doctor
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("doctor")
    def doctor_command(
        instance: Path | None = typer.Option(None, "--instance", help="Instance directory"),
    ) -> None:
        """Run environment and instance diagnostics."""
        instance_dir = instance.resolve() if instance is not None else None
        node = load_node_config(instance_dir) if instance_dir and (instance_dir / "node.yaml").exists() else None
        checks = run_doctor(instance_dir, node)
        failed = False
        for check in checks:
            status = "OK" if check.ok else "FAIL"
            typer.echo(f"[{status}] {check.name}: {check.detail}")
            if not check.ok:
                failed = True
        if failed:
            typer.echo("doctor found issues that may block apply/restart/status in this environment")
            raise typer.Exit(code=1)
