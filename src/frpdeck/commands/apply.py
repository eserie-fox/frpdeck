"""Apply command."""

from __future__ import annotations

from pathlib import Path

import typer

from frpdeck.domain.enums import Role
from frpdeck.domain.errors import CommandExecutionError, PermissionOperationError
from frpdeck.domain.state import ApplyState
from frpdeck.services.installer import ensure_binary_installed, sync_rendered_to_runtime
from frpdeck.services.renderer import render_instance
from frpdeck.services.systemd_manager import daemon_reload, enable_service, install_unit, restart_service
from frpdeck.services.verifier import validate_instance
from frpdeck.storage.dump import dump_json_data
from frpdeck.storage.file_lock import instance_lock
from frpdeck.storage.load import load_node_config, load_proxy_file


def register(app: typer.Typer) -> None:
    @app.command("apply")
    def apply_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        install_if_missing: bool = typer.Option(True, "--install-if-missing/--no-install-if-missing"),
    ) -> None:
        """Validate, render, install and restart an instance."""
        instance_dir = instance.resolve()
        with instance_lock(instance_dir / "state" / ".frpdeck.lock"):
            node = load_node_config(instance_dir)
            proxies = load_proxy_file(instance_dir) if node.role == Role.CLIENT else None
            errors = validate_instance(instance_dir, node, proxies)
            if errors:
                for error in errors:
                    typer.echo(f"ERROR: {error}")
                raise typer.Exit(code=1)
            summary = render_instance(instance_dir, node, proxies)
            try:
                if install_if_missing:
                    version = ensure_binary_installed(instance_dir, node)
                    typer.echo(f"binary version: {version}")
                config_path = sync_rendered_to_runtime(instance_dir, node)
                install_unit(summary.systemd_unit_path, node.resolved_paths(instance_dir).unit_path(node.service.service_name))
                daemon_reload()
                enable_service(node.service.service_name)
                restart_service(node.service.service_name)
            except PermissionOperationError as exc:
                typer.echo(f"ERROR: failed to apply {node.service.service_name}: {exc}")
                raise typer.Exit(code=1) from exc
            except CommandExecutionError as exc:
                typer.echo(f"ERROR: failed to apply {node.service.service_name}: {exc}")
                raise typer.Exit(code=1) from exc
            dump_json_data(
                ApplyState.create(node.service.service_name, config_path).model_dump(mode="json"),
                instance_dir / "state" / "last_apply.json",
            )
            typer.echo(f"applied {node.service.service_name}")
