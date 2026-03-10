"""Status helpers."""

from __future__ import annotations

from pathlib import Path

from frpdeck.domain.state import NodeBase
from frpdeck.domain.errors import CommandExecutionError
from frpdeck.domain.enums import Role
from frpdeck.domain.versioning import compare_versions
from frpdeck.services.installer import read_current_version
from frpdeck.services.runtime import run_command
from frpdeck.services.systemd_manager import status_service


def collect_status(instance_dir: Path, node: NodeBase) -> dict[str, str | None]:
    """Gather a lightweight status summary."""
    paths = node.resolved_paths(instance_dir)
    summary: dict[str, str | None] = {
        "instance_name": node.instance_name,
        "role": node.role.value,
        "service_name": node.service.service_name,
        "binary_path": str(paths.binary_path(node.role)),
        "config_path": str(paths.config_path(node.role)),
        "current_version": read_current_version(instance_dir),
    }
    if node.binary.version:
        target_version = node.binary.version
        summary["target_version"] = target_version
        comparison = compare_versions(summary["current_version"], target_version)
        if comparison is None:
            summary["update_available"] = "unknown"
            summary["version_note"] = "unable to compare current_version and target_version reliably"
        else:
            summary["update_available"] = "true" if comparison < 0 else "false"
    try:
        summary["systemd_status"] = status_service(node.service.service_name)
    except CommandExecutionError as exc:
        summary["systemd_status"] = f"unavailable: {exc}"

    if node.role == Role.CLIENT:
        if not paths.binary_path(node.role).exists():
            summary["frpc_status"] = f"frpc binary not found at {paths.binary_path(node.role)}; run apply or upgrade first"
        elif not paths.config_path(node.role).exists():
            summary["frpc_status"] = f"runtime config not found at {paths.config_path(node.role)}; run render/apply first"
        else:
            try:
                result = run_command(
                    [str(paths.binary_path(node.role)), "status", "-c", str(paths.config_path(node.role))],
                    check=False,
                )
                summary["frpc_status"] = result.stdout or result.stderr or "frpc status returned no output"
            except CommandExecutionError as exc:
                summary["frpc_status"] = f"unavailable: {exc}"
    return summary
