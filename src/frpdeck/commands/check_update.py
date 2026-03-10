"""Check-update command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.domain.versioning import compare_versions, normalize_version
from frpdeck.services.installer import read_current_version
from frpdeck.services.release_checker import get_release
from frpdeck.storage.load import load_node_config


def register(app: typer.Typer) -> None:
    @app.command("check-update")
    def check_update_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    ) -> None:
        """Check whether a newer binary is available."""
        instance_dir = instance.resolve()
        node = load_node_config(instance_dir)
        current = read_current_version(instance_dir)
        if node.binary.version:
            target = normalize_version(node.binary.version) or node.binary.version
            mode = "pinned"
        else:
            release = get_release(node.binary)
            target = release.version
            mode = "latest"
        comparison = compare_versions(current, target)
        if comparison is None:
            update_available = "unknown"
            comparison_note = "unable to compare current_version and target_version reliably"
        else:
            update_available = "true" if comparison < 0 else "false"
            comparison_note = None
        typer.echo(f"current_version: {current or 'unknown'}")
        typer.echo(f"target_version: {target}")
        typer.echo(f"mode: {mode}")
        typer.echo(f"update_available: {update_available}")
        if comparison_note:
            typer.echo(f"comparison_note: {comparison_note}")
