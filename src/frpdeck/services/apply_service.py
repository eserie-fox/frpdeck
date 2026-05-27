"""Apply workflow orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from frpdeck.domain.enums import Role
from frpdeck.domain.errors import FrpdeckError
from frpdeck.domain.paths import resolve_path_from_instance
from frpdeck.domain.state import ApplyState, NodeBase
from frpdeck.domain.proxy import ProxyFile
from frpdeck.services.installer import ensure_binary_installed, read_current_version, sync_rendered_to_runtime
from frpdeck.services.privilege import can_replace_directory, can_write_directory, can_write_file, root_owned_hint
from frpdeck.services.renderer import render_instance
from frpdeck.services.systemd_manager import daemon_reload, enable_service, install_unit, restart_service
from frpdeck.services.verifier import validate_instance
from frpdeck.storage.dump import dump_json_data
from frpdeck.storage.load import load_node_config, load_proxy_file


LOAD_CONFIG_STEP = "loading instance configuration"
VALIDATE_STEP = "validating instance configuration"
RENDER_STEP = "rendering configuration files"
INSTALL_BINARY_STEP = "ensuring FRP binary is installed"
SYNC_RUNTIME_STEP = "syncing rendered files into runtime directories"
INSTALL_UNIT_STEP = "installing or updating the systemd unit"
RESTART_SERVICE_STEP = "reloading systemd and restarting service"

_TOTAL_STEPS = 6


class ApplyProgressReporter(Protocol):
    """Minimal observer interface for apply progress updates."""

    def step_started(self, index: int, total: int, message: str) -> None: ...

    def step_succeeded(self, message: str) -> None: ...

    def step_skipped(self, message: str) -> None: ...

    def download_started(self, asset_name: str) -> None: ...

    def download_progress(self, downloaded_bytes: int, total_bytes: int | None) -> None: ...

    def download_finished(self, asset_name: str) -> None: ...


@dataclass(slots=True)
class ApplyExecutionResult:
    """Structured result for one apply workflow execution."""

    ok: bool
    service_name: str
    validation_errors: list[str] = field(default_factory=list)
    config_path: Path | None = None
    binary_version: str | None = None


class ApplyExecutionError(FrpdeckError):
    """Raised when one operational apply step fails."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


@dataclass(slots=True)
class _NullApplyProgressReporter:
    def step_started(self, index: int, total: int, message: str) -> None:
        return

    def step_succeeded(self, message: str) -> None:
        return

    def step_skipped(self, message: str) -> None:
        return

    def download_started(self, asset_name: str) -> None:
        return

    def download_progress(self, downloaded_bytes: int, total_bytes: int | None) -> None:
        return

    def download_finished(self, asset_name: str) -> None:
        return


class ApplyService:
    """Orchestrate validation, render, install, sync, and restart for one instance."""

    def apply_instance(
        self,
        instance_dir: Path,
        *,
        node: NodeBase | None = None,
        archive: Path | None = None,
        install_if_missing: bool = True,
        reporter: ApplyProgressReporter | None = None,
    ) -> ApplyExecutionResult:
        instance = instance_dir.resolve()
        progress = reporter or _NullApplyProgressReporter()

        resolved_node, proxies = self._load_apply_inputs(instance, node=node)

        progress.step_started(1, _TOTAL_STEPS, "Validating instance configuration...")
        validation_errors = self._run_step(
            VALIDATE_STEP,
            lambda: validate_instance(instance, resolved_node, proxies),
        )
        if validation_errors:
            return ApplyExecutionResult(
                ok=False,
                service_name=resolved_node.service.service_name,
                validation_errors=validation_errors,
            )
        progress.step_succeeded("Validation passed.")

        progress.step_started(2, _TOTAL_STEPS, "Rendering configuration files...")
        summary = self._run_step(
            RENDER_STEP,
            lambda: render_instance(instance, resolved_node, proxies),
        )
        progress.step_succeeded(f"Rendered files under {instance / 'rendered'}.")

        paths = resolved_node.resolved_paths(instance)
        binary_path = paths.binary_path(resolved_node.role)
        current_version = read_current_version(instance)
        explicit_archive = archive.resolve() if archive is not None else None

        progress.step_started(3, _TOTAL_STEPS, "Ensuring FRP binary is installed...")
        if install_if_missing:
            reusing_existing_binary = explicit_archive is None and binary_path.exists() and current_version is not None
            binary_version = self._run_step(
                INSTALL_BINARY_STEP,
                lambda: ensure_binary_installed(
                    instance,
                    resolved_node,
                    archive=explicit_archive,
                    progress=progress.download_progress,
                    download_started=progress.download_started,
                    download_finished=progress.download_finished,
                ),
            )
            if reusing_existing_binary:
                progress.step_skipped(f"Using existing {binary_path.name} binary version {binary_version}.")
            elif explicit_archive is not None:
                progress.step_succeeded(
                    f"Installed {binary_path.name} binary version {binary_version} from {explicit_archive}."
                )
            else:
                progress.step_succeeded(f"Installed {binary_path.name} binary version {binary_version}.")
        else:
            binary_version = current_version
            progress.step_skipped("Binary installation skipped by --no-install-if-missing.")

        progress.step_started(4, _TOTAL_STEPS, "Syncing rendered files into runtime directories...")
        config_path = self._run_step(
            SYNC_RUNTIME_STEP,
            lambda: sync_rendered_to_runtime(instance, resolved_node),
        )
        progress.step_succeeded(f"Updated FRP runtime config at {config_path}.")

        progress.step_started(5, _TOTAL_STEPS, "Installing/updating systemd unit...")
        self._run_step(
            INSTALL_UNIT_STEP,
            lambda: install_unit(
                summary.systemd_unit_path,
                paths.unit_path(resolved_node.service.service_name),
            ),
        )
        progress.step_succeeded(f"Installed unit at {paths.unit_path(resolved_node.service.service_name)}.")

        progress.step_started(6, _TOTAL_STEPS, "Reloading systemd and restarting service...")
        self._run_step(
            RESTART_SERVICE_STEP,
            lambda: self._reload_and_restart(resolved_node.service.service_name),
        )
        progress.step_succeeded(f"Service {resolved_node.service.service_name} is enabled and restarted.")

        dump_json_data(
            ApplyState.create(resolved_node.service.service_name, config_path).model_dump(mode="json"),
            instance / "state" / "last_apply.json",
        )

        return ApplyExecutionResult(
            ok=True,
            service_name=resolved_node.service.service_name,
            config_path=config_path,
            binary_version=binary_version,
        )

    def _load_apply_inputs(self, instance_dir: Path, *, node: NodeBase | None) -> tuple[NodeBase, ProxyFile | None]:
        try:
            resolved_node = node or load_node_config(instance_dir)
            proxies = load_proxy_file(instance_dir) if resolved_node.role == Role.CLIENT else None
        except Exception as exc:
            raise ApplyExecutionError(LOAD_CONFIG_STEP, str(exc)) from exc
        return resolved_node, proxies

    def _run_step(self, step: str, action):
        try:
            return action()
        except ApplyExecutionError:
            raise
        except Exception as exc:
            raise ApplyExecutionError(step, str(exc)) from exc

    def _reload_and_restart(self, service_name: str) -> None:
        daemon_reload()
        enable_service(service_name)
        restart_service(service_name)


def analyze_apply_root_requirements(
    instance_dir: Path,
    node: NodeBase,
    *,
    archive: Path | None = None,
    install_if_missing: bool = True,
) -> list[str]:
    """Return the reasons why one apply invocation requires root."""
    instance = instance_dir.resolve()
    paths = node.resolved_paths(instance)
    reasons: list[str] = []

    _append_reason(reasons, "will manage system service via systemctl")

    unit_path = paths.unit_path(node.service.service_name)
    if not can_write_file(unit_path):
        _append_reason(reasons, f"will write systemd unit under {paths.systemd_unit_dir}{root_owned_hint(unit_path)}")

    runtime_config_path = paths.config_path(node.role)
    if not can_write_file(runtime_config_path):
        _append_reason(
            reasons,
            f"runtime config path is not writable by current user: {runtime_config_path}{root_owned_hint(runtime_config_path)}",
        )

    if node.role == Role.CLIENT:
        runtime_proxies_dir = paths.proxies_dir()
        if not can_replace_directory(runtime_proxies_dir):
            _append_reason(
                reasons,
                f"runtime proxy include path is not writable by current user: {runtime_proxies_dir}{root_owned_hint(runtime_proxies_dir)}",
            )

    for log_dir in _frp_log_parent_dirs(instance, node):
        if not can_write_directory(log_dir):
            _append_reason(
                reasons, f"FRP log directory is not writable by current user: {log_dir}{root_owned_hint(log_dir)}"
            )

    rendered_root = instance / "rendered"
    if not can_write_directory(rendered_root):
        _append_reason(
            reasons,
            f"rendered output path is not writable by current user: {rendered_root}{root_owned_hint(rendered_root)}",
        )

    state_root = instance / "state"
    if not can_write_directory(state_root):
        _append_reason(
            reasons, f"state path is not writable by current user: {state_root}{root_owned_hint(state_root)}"
        )

    needs_binary_install = install_if_missing and _apply_will_install_binary(instance, node, archive=archive)
    if needs_binary_install and not can_write_directory(paths.install_dir):
        _append_reason(
            reasons,
            f"install path is not writable by current user: {paths.install_dir}{root_owned_hint(paths.install_dir)}",
        )

    backup_root = instance / "backups"
    if _apply_will_write_backups(paths, node) and not can_write_directory(backup_root):
        _append_reason(
            reasons, f"backup path is not writable by current user: {backup_root}{root_owned_hint(backup_root)}"
        )

    return reasons


def _apply_will_install_binary(instance_dir: Path, node: NodeBase, *, archive: Path | None) -> bool:
    if archive is not None:
        return True
    paths = node.resolved_paths(instance_dir)
    binary_path = paths.binary_path(node.role)
    current_version = read_current_version(instance_dir)
    return not binary_path.exists() or current_version is None


def _apply_will_write_backups(paths, node: NodeBase) -> bool:
    return paths.binary_path(node.role).exists() or paths.config_path(node.role).exists()


def _frp_log_parent_dirs(instance_dir: Path, node: NodeBase) -> list[Path]:
    log_target = node.client.log.to if node.role == Role.CLIENT else node.server.log.to
    if log_target is None:
        return []
    return [resolve_path_from_instance(log_target, instance_dir).parent]


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)
