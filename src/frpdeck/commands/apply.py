"""Apply command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import typer

from frpdeck.commands._download_progress import CliDownloadProgressReporter
from frpdeck.commands._invocation import build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges, unreadable_path_reason
from frpdeck.domain.errors import CommandExecutionError, ConfigLoadError, FrpdeckError, PermissionOperationError
from frpdeck.domain.enums import Role
from frpdeck.logging.daily_symlink import instance_logging_context
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
        ctx: typer.Context,
        instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
        archive: Path | None = typer.Option(None, "--archive", help="Offline frp tar.gz archive"),
        install_if_missing: bool = typer.Option(True, "--install-if-missing/--no-install-if-missing"),
        sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
    ) -> None:
        """Validate, render, sync, install, and restart an instance."""
        instance_dir = instance.resolve()
        resolved_archive = archive.resolve() if archive is not None else None
        invocation = build_command_invocation(
            ctx,
            overrides={
                "instance": instance_dir,
                "archive": resolved_archive,
            },
        )
        try:
            if maybe_reexec_with_sudo(
                operation="apply",
                sudo_requested=sudo,
                invocation=invocation,
            ):
                return
            preload_reasons: list[str] = []
            node_reason = unreadable_path_reason(instance_dir / "node.yaml", label="node config")
            if node_reason is not None:
                preload_reasons.append(node_reason)
            raise_for_missing_privileges(
                operation="apply",
                reasons=preload_reasons,
                invocation=invocation,
            )
            node = load_node_config(instance_dir)
            if node.role == Role.CLIENT:
                proxy_reason = unreadable_path_reason(instance_dir / "proxies.yaml", label="proxy config")
                if proxy_reason is not None:
                    preload_reasons.append(proxy_reason)
            raise_for_missing_privileges(
                operation="apply",
                reasons=preload_reasons
                + analyze_apply_root_requirements(
                    instance_dir,
                    node,
                    archive=resolved_archive,
                    install_if_missing=install_if_missing,
                ),
                invocation=invocation,
            )
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
