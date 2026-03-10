"""Subprocess helpers."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from frpdeck.domain.errors import CommandExecutionError


@dataclass(slots=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def command_exists(command: str) -> bool:
    """Return whether a command exists in PATH."""
    return shutil.which(command) is not None


def run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> CommandResult:
    """Run a command and capture output."""
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        command = " ".join(args)
        raise CommandExecutionError(f"command not found while executing: {command}\nreason: {exc}") from exc
    except OSError as exc:
        command = " ".join(args)
        raise CommandExecutionError(f"failed to execute command: {command}\nreason: {exc}") from exc
    result = CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )
    if check and completed.returncode != 0:
        raise CommandExecutionError(_format_command_failure(result))
    return result


def _format_command_failure(result: CommandResult) -> str:
    parts = [f"command failed ({result.returncode}): {' '.join(result.args)}"]
    if result.stdout:
        parts.append(f"stdout: {result.stdout}")
    if result.stderr:
        parts.append(f"stderr: {result.stderr}")
    return "\n".join(parts)
