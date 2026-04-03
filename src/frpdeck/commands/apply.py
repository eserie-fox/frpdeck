"""Apply command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import typer

from frpdeck.commands._download_progress import CliDownloadProgressReporter
from frpdeck.commands._privilege import ensure_root_privileges
from frpdeck.domain.errors import CommandExecutionError, ConfigLoadError, FrpdeckError, PermissionOperationError
from frpdeck.logging import instance_logging_context
from frpdeck.services.apply_service import (
    ApplyExecutionError,
    ApplyProgressReporter,
    ApplyService,
    LOAD_CONFIG_STEP,
    analyze_apply_root_requirements,
)
from frpdeck.storage.file_lock import instance_lock
from frpdeck.storage.load import load_node_config

@dataclass(slots=True)
class _CliApplyReporter(ApplyProgressReporter):
    echo: Callable[[str], None]
    _download: CliDownloadProgressReporter = field(init=False)

    def __post_init__(self) -> None:
        self._download = CliDownloadProgressReporter(self.echo)

    def step_started(self, index: int, total: int, message: str) -> None:
        self.echo(f"[{index}/{total}] {message}")

    def step_succeeded(self, message: str) -> None:
        self.echo(f"OK: {message}")

    def step_skipped(self, message: str) -> None:
        self.echo(f"SKIP: {message}")

    def download_started(self, asset_name: str) -> None:
        self._download.start(asset_name)

    def download_progress(self, downloaded_bytes: int, total_bytes: int | None) -> None:
        self._download.update(downloaded_bytes, total_bytes)

    def download_finished(self, asset_name: str) -> None:
        self._download.finish(asset_name)


def register(app: typer.Typer) -> None:
    @app.command("apply")
    def apply_command(
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        archive: Path | None = typer.Option(None, "--archive", help="Offline frp tar.gz archive"),
        install_if_missing: bool = typer.Option(True, "--install-if-missing/--no-install-if-missing"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Validate, render, sync, install, and restart an instance."""
        instance_dir = instance.resolve()
        try:
            node = load_node_config(instance_dir)
            if ensure_root_privileges(
                operation="apply",
                reasons=analyze_apply_root_requirements(
                    instance_dir,
                    node,
                    archive=archive.resolve() if archive is not None else None,
                    install_if_missing=install_if_missing,
                ),
                sudo_requested=sudo,
                command_args=_apply_command_args(
                    instance_dir,
                    archive=archive.resolve() if archive is not None else None,
                    install_if_missing=install_if_missing,
                ),
            ):
                return
            with instance_lock(instance_dir / "state" / ".frpdeck.lock"):
                with instance_logging_context(instance_dir, node=node):
                    result = ApplyService().apply_instance(
                        instance_dir,
                        node=node,
                        archive=archive,
                        install_if_missing=install_if_missing,
                        reporter=_CliApplyReporter(typer.echo),
                    )
                if not result.ok:
                    for error in result.validation_errors:
                        typer.echo(f"ERROR: {error}")
                    raise typer.Exit(code=1)
                typer.echo("Apply completed successfully.")
        except typer.Exit:
            raise
        except ApplyExecutionError as exc:
            typer.echo(f"ERROR: apply failed during {exc.step}: {exc}")
            raise typer.Exit(code=1) from exc
        except PermissionOperationError as exc:
            typer.echo(f"ERROR: {exc}")
            raise typer.Exit(code=1) from exc
        except (ConfigLoadError, CommandExecutionError, FrpdeckError) as exc:
            typer.echo(f"ERROR: apply failed during {LOAD_CONFIG_STEP}: {exc}")
            raise typer.Exit(code=1) from exc


def _apply_command_args(instance_dir: Path, *, archive: Path | None, install_if_missing: bool) -> list[str]:
    args = ["apply", "--instance", str(instance_dir)]
    if archive is not None:
        args.extend(["--archive", str(archive)])
    if not install_if_missing:
        args.append("--no-install-if-missing")
    return args
