"""Privilege checks and sudo re-exec helpers for mutating commands."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import sys

from frpdeck.domain.errors import PermissionOperationError
from frpdeck.services.runtime import command_exists


def current_user_is_root() -> bool:
    """Return whether the current process is running as root."""
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return False
    return geteuid() == 0


def ensure_root_privileges(
    *,
    operation: str,
    reasons: list[str],
    sudo_requested: bool,
    command_args: list[str],
) -> bool:
    """Fail fast or re-exec through sudo when root is required."""
    if current_user_is_root() or not reasons:
        return False

    if not sudo_requested:
        raise PermissionOperationError(_format_privilege_message(operation, reasons, command_args))

    if not command_exists("sudo"):
        raise PermissionOperationError(
            _format_privilege_message(
                operation,
                reasons,
                command_args,
                sudo_requested=True,
                sudo_available=False,
            )
        )

    _exec_with_sudo(_sudo_exec_args(command_args))
    return True


def _format_privilege_message(
    operation: str,
    reasons: list[str],
    command_args: list[str],
    *,
    sudo_requested: bool = False,
    sudo_available: bool = True,
) -> str:
    manual_command = _display_command(command_args)
    retry_command = _display_command([*command_args, "--sudo"])
    lines = [f"{operation} requires elevated privileges for this instance:"]
    lines.extend(f"- {reason}" for reason in reasons)
    if sudo_requested and not sudo_available:
        lines.append("`--sudo` was requested, but `sudo` is not available in PATH.")
        lines.append(f"Run this command as root instead: {manual_command}")
    else:
        lines.append(f"Retry with: {retry_command}")
        lines.append(f"Or run manually: sudo {manual_command}")
    return "\n".join(lines)


def _display_command(command_args: list[str]) -> str:
    return shlex.join(["frpdeck", *command_args])


def _sudo_exec_args(command_args: list[str]) -> list[str]:
    cli_path = Path(sys.executable).resolve().with_name("frpdeck")
    if cli_path.exists() and os.access(cli_path, os.X_OK):
        return ["sudo", str(cli_path), *command_args, "--sudo"]
    return ["sudo", sys.executable, "-m", "frpdeck", *command_args, "--sudo"]


def _exec_with_sudo(args: list[str]) -> None:
    os.execvp(args[0], args)

