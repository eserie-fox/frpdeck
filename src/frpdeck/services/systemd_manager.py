"""systemd operations."""

from __future__ import annotations

from pathlib import Path
import shutil

from frpdeck.domain.errors import PermissionOperationError
from frpdeck.services.runtime import CommandResult, run_command


def install_unit(rendered_unit: Path, target_unit: Path) -> None:
    """Copy a rendered unit file into the configured systemd directory."""
    try:
        target_unit.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rendered_unit, target_unit)
    except PermissionError as exc:
        raise PermissionOperationError(
            f"cannot write systemd unit to {target_unit}; use sudo or change paths.systemd_unit_dir"
        ) from exc


def daemon_reload() -> None:
    run_command(["systemctl", "daemon-reload"])


def enable_service(service_name: str) -> None:
    run_command(["systemctl", "enable", f"{service_name}.service"])


def disable_service(service_name: str, *, check: bool = True) -> CommandResult:
    return run_command(["systemctl", "disable", f"{service_name}.service"], check=check)


def stop_service(service_name: str, *, check: bool = True) -> CommandResult:
    return run_command(["systemctl", "stop", f"{service_name}.service"], check=check)


def restart_service(service_name: str) -> None:
    run_command(["systemctl", "restart", f"{service_name}.service"])


def remove_unit_file(target_unit: Path) -> None:
    try:
        if target_unit.exists():
            target_unit.unlink()
    except PermissionError as exc:
        raise PermissionOperationError(
            f"cannot remove systemd unit at {target_unit}; use sudo or change paths.systemd_unit_dir"
        ) from exc


def status_service(service_name: str) -> str:
    result = run_command(["systemctl", "status", f"{service_name}.service", "--no-pager", "--lines=10"], check=False)
    return (result.stdout or result.stderr).strip()
