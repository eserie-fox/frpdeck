"""Binary install and rendered-file apply helpers."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
from collections.abc import Callable

from frpdeck.domain.enums import Role
from frpdeck.domain.errors import ConfigValidationError, PermissionOperationError
from frpdeck.domain.paths import resolve_path_from_instance
from frpdeck.domain.state import InstallState, NodeBase
from frpdeck.domain.versioning import normalize_version
from frpdeck.storage.dump import dump_json_data
from frpdeck.services.backup import backup_file_if_exists
from frpdeck.services.downloader import DownloadProgressCallback, download_file
from frpdeck.services.privilege import (
    can_execute_file,
    can_read_path,
    can_replace_directory,
    can_write_directory,
    can_write_file,
    root_owned_hint,
)
from frpdeck.services.release_checker import ReleaseInfo, get_release


DownloadStageCallback = Callable[[str], None]


def ensure_binary_installed(
    instance_dir: Path,
    node: NodeBase,
    *,
    archive: Path | None = None,
    progress: DownloadProgressCallback | None = None,
    download_started: DownloadStageCallback | None = None,
    download_finished: DownloadStageCallback | None = None,
) -> str:
    """Install the binary if missing and return the active version."""
    paths = node.resolved_paths(instance_dir)
    binary_path = paths.binary_path(node.role)
    current_version = read_current_version(instance_dir)
    if archive is not None:
        return install_from_archive(instance_dir, node, archive.resolve(), node.binary.version)
    if binary_path.exists() and current_version:
        return current_version
    local_archive = node.binary.local_archive
    if local_archive is not None:
        resolved_archive = local_archive if local_archive.is_absolute() else (instance_dir / local_archive).resolve()
        return install_from_archive(instance_dir, node, resolved_archive, node.binary.version)
    release = get_release(node.binary)
    return install_from_release(
        instance_dir,
        node,
        release,
        progress=progress,
        download_started=download_started,
        download_finished=download_finished,
    )


def install_from_release(
    instance_dir: Path,
    node: NodeBase,
    release: ReleaseInfo,
    *,
    progress: DownloadProgressCallback | None = None,
    download_started: DownloadStageCallback | None = None,
    download_finished: DownloadStageCallback | None = None,
) -> str:
    """Download and install a release asset."""
    with tempfile.TemporaryDirectory(prefix="frpdeck-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        if download_started is not None:
            download_started(release.asset_name)
        archive_path = download_file(
            release.asset_url,
            temp_dir / release.asset_name,
            progress=progress,
        )
        if download_finished is not None:
            download_finished(release.asset_name)
        return install_from_archive(instance_dir, node, archive_path, release.version)


def install_from_archive(instance_dir: Path, node: NodeBase, archive_path: Path, version_hint: str | None) -> str:
    """Install frpc/frps from a local archive."""
    if not archive_path.exists():
        raise ConfigValidationError(f"archive not found: {archive_path}")

    paths = node.resolved_paths(instance_dir)
    binary_path = paths.binary_path(node.role)
    backup_dir = instance_dir / "backups"
    executable_name = binary_path.name

    with tempfile.TemporaryDirectory(prefix="frpdeck-extract-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        with tarfile.open(archive_path, mode="r:gz") as tar:
            tar.extractall(temp_dir)

        candidates = list(temp_dir.rglob(executable_name))
        if not candidates:
            raise ConfigValidationError(f"archive does not contain {executable_name}")
        source_binary = candidates[0]
        try:
            paths.install_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise PermissionOperationError(
                f"cannot write install_dir {paths.install_dir}; use sudo or change paths.install_dir"
            ) from exc

        backup_file_if_exists(binary_path, backup_dir)
        temp_target = binary_path.with_suffix(".tmp")
        shutil.copy2(source_binary, temp_target)
        temp_target.chmod(0o755)
        os.replace(temp_target, binary_path)

    version = normalize_version(version_hint) or _version_from_archive_name(archive_path.name)
    write_current_version(instance_dir, version)
    dump_json_data(
        InstallState.create(version=version, binary_path=binary_path).model_dump(mode="json"),
        instance_dir / "state" / "install.json",
    )
    return version


def sync_rendered_to_runtime(instance_dir: Path, node: NodeBase) -> Path:
    """Copy rendered config artifacts into configured runtime paths."""
    paths = node.resolved_paths(instance_dir)
    rendered_dir = instance_dir / "rendered"
    rendered_main = rendered_dir / ("frpc.toml" if node.role == Role.CLIENT else "frps.toml")
    rendered_proxies = rendered_dir / "proxies.d"
    _validate_rendered_snapshot(node, rendered_main=rendered_main, rendered_proxies=rendered_proxies)

    try:
        paths.config_root.mkdir(parents=True, exist_ok=True)
        for log_dir in _runtime_log_dirs(instance_dir, node):
            log_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise PermissionOperationError(
            "cannot create runtime configuration or FRP log directories; use sudo or adjust configured paths"
        ) from exc

    target_main = paths.config_path(node.role)
    try:
        backup_file_if_exists(target_main, instance_dir / "backups")
        shutil.copy2(rendered_main, target_main)
    except PermissionError as exc:
        raise PermissionOperationError(
            f"cannot update runtime main config {target_main}; use sudo or adjust configured paths"
        ) from exc

    target_proxies = paths.proxies_dir()
    if node.role == Role.CLIENT:
        try:
            if target_proxies.exists():
                shutil.rmtree(target_proxies)
            shutil.copytree(rendered_proxies, target_proxies)
        except PermissionError as exc:
            raise PermissionOperationError(
                f"cannot replace runtime proxy include directory {target_proxies}; use sudo or adjust configured paths"
            ) from exc
    return target_main


def analyze_sync_root_requirements(instance_dir: Path, node: NodeBase) -> list[str]:
    """Return the reasons why one sync invocation requires root."""

    instance = instance_dir.resolve()
    paths = node.resolved_paths(instance)
    reasons: list[str] = []
    lock_path = instance / "state" / ".frpdeck.lock"

    if not can_write_file(lock_path):
        reasons.append(f"instance lock path is not writable by current user: {lock_path}{root_owned_hint(lock_path)}")

    runtime_config_path = paths.config_path(node.role)
    if not can_write_file(runtime_config_path):
        reasons.append(
            f"runtime config path is not writable by current user: {runtime_config_path}{root_owned_hint(runtime_config_path)}"
        )

    if node.role == Role.CLIENT:
        runtime_proxies_dir = paths.proxies_dir()
        if not can_replace_directory(runtime_proxies_dir):
            reasons.append(
                f"runtime proxy include path is not writable by current user: {runtime_proxies_dir}{root_owned_hint(runtime_proxies_dir)}"
            )

    backup_root = instance / "backups"
    if runtime_config_path.exists() and not can_write_directory(backup_root):
        reasons.append(f"backup path is not writable by current user: {backup_root}{root_owned_hint(backup_root)}")

    for log_dir in _runtime_log_dirs(instance, node):
        if not can_write_directory(log_dir):
            reasons.append(f"FRP log directory is not writable by current user: {log_dir}{root_owned_hint(log_dir)}")

    rendered_main = instance / "rendered" / ("frpc.toml" if node.role == Role.CLIENT else "frps.toml")
    if rendered_main.exists() and not can_read_path(rendered_main):
        reasons.append(
            f"rendered main config is not readable by current user: {rendered_main}{root_owned_hint(rendered_main)}"
        )

    if node.role == Role.CLIENT:
        rendered_proxies = instance / "rendered" / "proxies.d"
        if rendered_proxies.exists() and not can_read_path(rendered_proxies):
            reasons.append(
                f"rendered proxy include directory is not readable by current user: {rendered_proxies}{root_owned_hint(rendered_proxies)}"
            )

    return reasons


def analyze_reload_root_requirements(instance_dir: Path, node: NodeBase) -> list[str]:
    """Return the reasons why one reload invocation requires elevated privileges."""
    instance = instance_dir.resolve()
    paths = node.resolved_paths(instance)
    reasons: list[str] = []
    binary_path = paths.binary_path(node.role)
    config_path = paths.config_path(node.role)

    if binary_path.exists() and not can_execute_file(binary_path):
        reasons.append(f"frpc binary is not executable by current user: {binary_path}{root_owned_hint(binary_path)}")

    if config_path.exists() and not can_read_path(config_path):
        reasons.append(
            f"runtime config path is not readable by current user: {config_path}{root_owned_hint(config_path)}"
        )

    if node.role == Role.CLIENT:
        runtime_proxies_dir = paths.proxies_dir()
        if runtime_proxies_dir.exists() and not can_read_path(runtime_proxies_dir):
            reasons.append(
                f"runtime proxy include path is not readable by current user: {runtime_proxies_dir}{root_owned_hint(runtime_proxies_dir)}"
            )

    return reasons


def analyze_upgrade_root_requirements(
    instance_dir: Path,
    node: NodeBase,
    *,
    archive: Path | None = None,
    restart_after: bool = True,
) -> list[str]:
    """Return the reasons why one upgrade invocation requires elevated privileges."""
    instance = instance_dir.resolve()
    paths = node.resolved_paths(instance)
    reasons: list[str] = []
    lock_path = instance / "state" / ".frpdeck.lock"
    state_root = instance / "state"
    backup_root = instance / "backups"

    if not can_write_file(lock_path):
        reasons.append(f"instance lock path is not writable by current user: {lock_path}{root_owned_hint(lock_path)}")

    if not can_write_directory(paths.install_dir):
        reasons.append(
            f"install path is not writable by current user: {paths.install_dir}{root_owned_hint(paths.install_dir)}"
        )

    if not can_write_directory(state_root):
        reasons.append(f"state path is not writable by current user: {state_root}{root_owned_hint(state_root)}")

    current_version_path = state_root / "current_version.txt"
    if current_version_path.exists() and not can_write_file(current_version_path):
        reasons.append(
            f"current version state file is not writable by current user: {current_version_path}{root_owned_hint(current_version_path)}"
        )

    if paths.binary_path(node.role).exists() and not can_write_directory(backup_root):
        reasons.append(f"backup path is not writable by current user: {backup_root}{root_owned_hint(backup_root)}")

    if archive is not None and archive.exists() and not can_read_path(archive):
        reasons.append(f"archive is not readable by current user: {archive}{root_owned_hint(archive)}")
    elif archive is None and node.binary.local_archive is not None:
        resolved_archive = (
            node.binary.local_archive
            if node.binary.local_archive.is_absolute()
            else (instance / node.binary.local_archive).resolve()
        )
        if resolved_archive.exists() and not can_read_path(resolved_archive):
            reasons.append(
                f"archive is not readable by current user: {resolved_archive}{root_owned_hint(resolved_archive)}"
            )

    if restart_after:
        reasons.append("will manage system service via systemctl")

    return reasons


def write_current_version(instance_dir: Path, version: str) -> None:
    """Persist the current version string."""
    state_dir = instance_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    normalized = normalize_version(version) or version.strip()
    (state_dir / "current_version.txt").write_text(normalized + "\n", encoding="utf-8")


def read_current_version(instance_dir: Path) -> str | None:
    """Read the installed version if present."""
    path = instance_dir / "state" / "current_version.txt"
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    return normalize_version(content) or content or None


def _version_from_archive_name(archive_name: str) -> str:
    match = re.search(r"frp_(?:v)?(?P<version>\d+(?:\.\d+)+)_[^_]+_[^_]+\.tar\.gz$", archive_name)
    if not match:
        return "unknown"
    return normalize_version(match.group("version")) or "unknown"


def _runtime_log_dirs(instance_dir: Path, node: NodeBase) -> list[Path]:
    if node.role == Role.CLIENT:
        log_target = node.client.log.to
    else:
        log_target = node.server.log.to
    if log_target is None:
        return []
    return [resolve_path_from_instance(log_target, instance_dir).parent]


def _validate_rendered_snapshot(
    node: NodeBase,
    *,
    rendered_main: Path,
    rendered_proxies: Path,
) -> None:
    if not rendered_main.exists() or not rendered_main.is_file():
        raise ConfigValidationError(f"rendered main config not found: {rendered_main}; run render first")
    if node.role == Role.CLIENT and (not rendered_proxies.exists() or not rendered_proxies.is_dir()):
        raise ConfigValidationError(f"rendered proxy include directory not found: {rendered_proxies}; run render first")
