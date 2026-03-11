"""Apply command."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

import typer

from frpdeck.domain.enums import Role
from frpdeck.domain.errors import CommandExecutionError, ConfigLoadError, FrpdeckError, PermissionOperationError
from frpdeck.domain.state import ApplyState
from frpdeck.services.installer import ensure_binary_installed, read_current_version, sync_rendered_to_runtime
from frpdeck.services.renderer import render_instance
from frpdeck.services.systemd_manager import daemon_reload, enable_service, install_unit, restart_service
from frpdeck.services.verifier import validate_instance
from frpdeck.storage.dump import dump_json_data
from frpdeck.storage.file_lock import instance_lock
from frpdeck.storage.load import load_node_config, load_proxy_file


StepResult = TypeVar("StepResult")


def _echo_step(index: int, total: int, message: str) -> None:
    typer.echo(f"[{index}/{total}] {message}")


def _echo_success(message: str) -> None:
    typer.echo(f"OK: {message}")


def _echo_skip(message: str) -> None:
    typer.echo(f"SKIP: {message}")


def _run_step(index: int, total: int, message: str, action: Callable[[], StepResult]) -> StepResult:
    _echo_step(index, total, message)
    return action()


def register(app: typer.Typer) -> None:
    @app.command("apply")
    def apply_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        install_if_missing: bool = typer.Option(True, "--install-if-missing/--no-install-if-missing"),
    ) -> None:
        """Validate, render, install and restart an instance."""
        instance_dir = instance.resolve()
        current_step = "loading instance configuration"
        try:
            with instance_lock(instance_dir / "state" / ".frpdeck.lock"):
                node = load_node_config(instance_dir)
                proxies = load_proxy_file(instance_dir) if node.role == Role.CLIENT else None

                current_step = "validating instance configuration"
                errors = _run_step(
                    1,
                    6,
                    "Validating instance configuration...",
                    lambda: validate_instance(instance_dir, node, proxies),
                )
                if errors:
                    for error in errors:
                        typer.echo(f"ERROR: {error}")
                    raise typer.Exit(code=1)
                _echo_success("Validation passed.")

                current_step = "rendering configuration files"
                summary = _run_step(
                    2,
                    6,
                    "Rendering configuration files...",
                    lambda: render_instance(instance_dir, node, proxies),
                )
                _echo_success(f"Rendered files under {instance_dir / 'rendered'}.")

                current_step = "ensuring FRP binary is installed"
                paths = node.resolved_paths(instance_dir)
                binary_path = paths.binary_path(node.role)
                current_version = read_current_version(instance_dir)
                if install_if_missing:
                    version = _run_step(
                        3,
                        6,
                        "Ensuring FRP binary is installed...",
                        lambda: ensure_binary_installed(instance_dir, node),
                    )
                    if binary_path.exists() and current_version:
                        _echo_skip(f"Using existing {binary_path.name} binary version {version}.")
                    else:
                        _echo_success(f"Installed {binary_path.name} binary version {version}.")
                else:
                    _echo_step(3, 6, "Ensuring FRP binary is installed...")
                    _echo_skip("Binary installation skipped by --no-install-if-missing.")

                current_step = "syncing rendered files into runtime directories"
                config_path = _run_step(
                    4,
                    6,
                    "Syncing rendered files into runtime directories...",
                    lambda: sync_rendered_to_runtime(instance_dir, node),
                )
                _echo_success(f"Updated runtime config at {config_path}.")

                current_step = "installing or updating the systemd unit"
                _run_step(
                    5,
                    6,
                    "Installing/updating systemd unit...",
                    lambda: install_unit(
                        summary.systemd_unit_path,
                        paths.unit_path(node.service.service_name),
                    ),
                )
                _echo_success(f"Installed unit at {paths.unit_path(node.service.service_name)}.")

                current_step = "reloading systemd and restarting service"
                _run_step(
                    6,
                    6,
                    "Reloading systemd and restarting service...",
                    lambda: (
                        daemon_reload(),
                        enable_service(node.service.service_name),
                        restart_service(node.service.service_name),
                    ),
                )
                _echo_success(f"Service {node.service.service_name} is enabled and restarted.")

                dump_json_data(
                    ApplyState.create(node.service.service_name, config_path).model_dump(mode="json"),
                    instance_dir / "state" / "last_apply.json",
                )
                typer.echo("Apply completed successfully.")
        except typer.Exit:
            raise
        except (ConfigLoadError, PermissionOperationError, CommandExecutionError, FrpdeckError) as exc:
            typer.echo(f"ERROR: apply failed during {current_step}: {exc}")
            raise typer.Exit(code=1) from exc
