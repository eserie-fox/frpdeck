"""Instance uninstall helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil

from frpdeck.domain.errors import ConfigValidationError, PermissionOperationError
from frpdeck.services.runtime import command_exists
from frpdeck.services.systemd_manager import daemon_reload, disable_service, remove_unit_file, stop_service
from frpdeck.storage.load import load_node_config


_DANGEROUS_DELETE_PATHS = {
    Path("/"),
    Path("/boot"),
    Path("/dev"),
    Path("/etc"),
    Path("/home"),
    Path("/lib"),
    Path("/lib64"),
    Path("/opt"),
    Path("/proc"),
    Path("/root"),
    Path("/run"),
    Path("/srv"),
    Path("/sys"),
    Path("/tmp"),
    Path("/usr"),
    Path("/var"),
}


@dataclass(slots=True)
class UninstallReport:
    service_name: str
    unit_path: Path
    systemctl_available: bool
    service_stopped: bool = False
    service_disabled: bool = False
    unit_removed: bool = False
    removed_paths: list[Path] = field(default_factory=list)
    kept_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    instance_deleted: bool = False


def uninstall_instance(instance_dir: Path, purge: bool = False) -> UninstallReport:
    """Remove installed runtime artifacts for an instance."""
    instance = instance_dir.resolve()
    node = load_node_config(instance)
    paths = node.resolved_paths(instance)
    unit_path = paths.unit_path(node.service.service_name)
    report = UninstallReport(
        service_name=node.service.service_name,
        unit_path=unit_path,
        systemctl_available=command_exists("systemctl"),
    )

    _assert_safe_delete_path(instance, allow_instance_root=purge)

    if report.systemctl_available:
        stop_result = stop_service(node.service.service_name, check=False)
        if stop_result.returncode == 0:
            report.service_stopped = True
        elif stop_result.stderr:
            report.warnings.append(f"could not stop service cleanly: {stop_result.stderr}")

        disable_result = disable_service(node.service.service_name, check=False)
        if disable_result.returncode == 0:
            report.service_disabled = True
        elif disable_result.stderr:
            report.warnings.append(f"could not disable service cleanly: {disable_result.stderr}")
    else:
        report.warnings.append("systemctl not available; skipped stop/disable/daemon-reload")

    cleanup_paths = _runtime_cleanup_paths(instance, paths.install_dir, paths.config_root, paths.log_dir, paths.runtime_dir)
    install_cleanup_target, install_warning = _resolve_install_cleanup_target(
        instance,
        paths.install_dir,
        paths.binary_path(node.role),
        node.instance_name,
        report.service_name,
        cleanup_paths,
    )
    _validate_delete_targets(
        [
            unit_path if unit_path.exists() else None,
            *cleanup_paths,
            instance / "rendered",
            instance / "state",
            instance / "backups",
            install_cleanup_target,
            instance if purge else None,
        ],
        instance,
        purge,
    )

    if unit_path.exists():
        remove_unit_file(unit_path)
        report.unit_removed = True

    if report.systemctl_available:
        daemon_reload()

    for path in cleanup_paths:
        _remove_path(path, report)

    for path in [instance / "rendered", instance / "state", instance / "backups"]:
        _remove_path(path, report)

    if install_cleanup_target is not None:
        _remove_path(install_cleanup_target, report)
    elif install_warning is not None:
        report.warnings.append(install_warning)

    if purge:
        _remove_path(instance, report, allow_instance_root=True)
        report.instance_deleted = True
        return report

    for path in [instance / "node.yaml", instance / "proxies.yaml", instance / "secrets"]:
        if path.exists():
            report.kept_paths.append(path)
    report.kept_paths.append(instance)
    return report


def _runtime_cleanup_paths(instance: Path, install_dir: Path, config_root: Path, log_dir: Path, runtime_dir: Path) -> list[Path]:
    candidates = [install_dir, config_root, log_dir, runtime_dir]
    unique_paths: list[Path] = []
    for path in candidates:
        if any(_is_relative_to(path, existing) for existing in unique_paths):
            continue
        unique_paths = [existing for existing in unique_paths if not _is_relative_to(existing, path)]
        unique_paths.append(path)
    shared_parent = _shared_parent(unique_paths)
    if shared_parent is not None and shared_parent != instance:
        return [shared_parent]
    unique_paths.sort(key=lambda item: (0 if _is_relative_to(item, instance) else 1, len(item.parts)))
    return unique_paths


def _resolve_install_cleanup_target(
    instance: Path,
    install_dir: Path,
    binary_path: Path,
    instance_name: str,
    service_name: str,
    cleanup_paths: list[Path],
) -> tuple[Path | None, str | None]:
    if any(_is_relative_to(install_dir, cleanup_path) for cleanup_path in cleanup_paths):
        return None, None
    if _is_relative_to(install_dir, instance):
        return install_dir, None
    if binary_path.exists() and _looks_instance_private(binary_path.parent, instance_name, service_name):
        return binary_path, None
    return None, f"kept install artifacts under shared path: {install_dir}"


def _looks_instance_private(path: Path, instance_name: str, service_name: str) -> bool:
    names = {part.lower() for part in path.parts}
    return instance_name.lower() in names or service_name.lower() in names


def _remove_path(path: Path, report: UninstallReport, *, allow_instance_root: bool = False) -> None:
    resolved = path.resolve()
    if not resolved.exists():
        return
    _assert_safe_delete_path(resolved, allow_instance_root=allow_instance_root)
    try:
        if resolved.is_dir() and not resolved.is_symlink():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
    except PermissionError as exc:
        raise PermissionOperationError(f"cannot delete {resolved}; use sudo or adjust configured paths") from exc
    report.removed_paths.append(resolved)


def _assert_safe_delete_path(path: Path, *, allow_instance_root: bool = False) -> None:
    resolved = path.resolve()
    if resolved in _DANGEROUS_DELETE_PATHS:
        raise ConfigValidationError(f"refusing to delete dangerous path: {resolved}")
    if len(resolved.parts) <= 2:
        raise ConfigValidationError(f"refusing to delete overly broad path: {resolved}")
    if resolved == resolved.parent:
        raise ConfigValidationError(f"refusing to delete filesystem root: {resolved}")
    if not allow_instance_root and resolved.name in {"", ".", ".."}:
        raise ConfigValidationError(f"refusing to delete ambiguous path: {resolved}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _shared_parent(paths: list[Path]) -> Path | None:
    if len(paths) <= 1:
        return None
    parent = paths[0].parent
    if any(path.parent != parent for path in paths):
        return None
    return parent


def _validate_delete_targets(targets: list[Path | None], instance: Path, purge: bool) -> None:
    for target in targets:
        if target is None or not target.exists():
            continue
        _assert_safe_delete_path(target, allow_instance_root=purge and target == instance)