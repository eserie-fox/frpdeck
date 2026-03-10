"""Binary install and rendered-file apply helpers."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from frpdeck.domain.errors import ConfigValidationError, PermissionOperationError
from frpdeck.domain.state import InstallState, NodeBase
from frpdeck.domain.versioning import normalize_version
from frpdeck.storage.dump import dump_json_data
from frpdeck.services.backup import backup_file_if_exists
from frpdeck.services.downloader import download_file
from frpdeck.services.release_checker import ReleaseInfo, get_release


def ensure_binary_installed(instance_dir: Path, node: NodeBase) -> str:
    """Install the binary if missing and return the active version."""
    paths = node.resolved_paths(instance_dir)
    binary_path = paths.binary_path(node.role)
    current_version = read_current_version(instance_dir)
    if binary_path.exists() and current_version:
        return current_version
    archive = node.binary.local_archive
    if archive is not None:
        resolved_archive = archive if archive.is_absolute() else (instance_dir / archive).resolve()
        return install_from_archive(instance_dir, node, resolved_archive, node.binary.version)
    release = get_release(node.binary)
    return install_from_release(instance_dir, node, release)


def install_from_release(instance_dir: Path, node: NodeBase, release: ReleaseInfo) -> str:
    """Download and install a release asset."""
    with tempfile.TemporaryDirectory(prefix="frpdeck-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        archive_path = download_file(release.asset_url, temp_dir / release.asset_name)
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
    rendered_main = rendered_dir / ("frpc.toml" if node.role.value == "client" else "frps.toml")
    rendered_proxies = rendered_dir / "proxies.d"

    try:
        paths.config_root.mkdir(parents=True, exist_ok=True)
        paths.log_dir.mkdir(parents=True, exist_ok=True)
        paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise PermissionOperationError(
            f"cannot create runtime directories under {paths.config_root.parent}; use sudo or adjust paths"
        ) from exc

    target_main = paths.config_path(node.role)
    backup_file_if_exists(target_main, instance_dir / "backups")
    shutil.copy2(rendered_main, target_main)

    target_proxies = paths.proxies_dir()
    if rendered_proxies.exists():
        if target_proxies.exists():
            shutil.rmtree(target_proxies)
        shutil.copytree(rendered_proxies, target_proxies)
    return target_main


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
