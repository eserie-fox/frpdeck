"""MCP helper commands for stdio wrapper installation."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

import os

import typer

from frpdeck.services.audit import build_actor, record_audit_event
from frpdeck.storage.file_lock import instance_lock


WRAPPER_FILENAME = "start-mcp-stdio.sh"
DEFAULT_SSH_HOST = "grape_networking"

mcp_app = typer.Typer(help="MCP stdio helper commands")


def register(app: typer.Typer) -> None:
    app.add_typer(mcp_app, name="mcp")


def render_stdio_wrapper(instance_dir: Path, *, python_executable: Path, workdir: Path) -> str:
    """Render the bound stdio MCP wrapper script content."""
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "# This wrapper starts the frpdeck stdio MCP server for one bound instance.",
            "# It uses the Python interpreter detected when the wrapper was generated.",
            "# If this fails in a uv or virtualenv-managed environment, regenerate the wrapper",
            "# from that environment or edit the script to activate it first.",
            "set -euo pipefail",
            f"PYTHON_BIN={shlex.quote(str(python_executable))}",
            f"INSTANCE_DIR={shlex.quote(str(instance_dir))}",
            f"cd {shlex.quote(str(workdir))}",
            'if [[ ! -x "$PYTHON_BIN" ]]; then',
            '  echo "frpdeck MCP wrapper error: Python interpreter is missing or not executable: $PYTHON_BIN" >&2',
            '  echo "Regenerate this wrapper from the target environment, or edit the script to activate the correct uv or virtualenv environment first." >&2',
            '  exit 127',
            'fi',
            'if "$PYTHON_BIN" -m frpdeck.mcp.server --instance-dir "$INSTANCE_DIR"; then',
            '  exit 0',
            'else',
            '  rc=$?',
            '  echo "frpdeck MCP wrapper error: failed to start the bound stdio MCP server." >&2',
            '  echo "If this host uses uv or virtualenv, verify that the embedded Python interpreter is valid here." >&2',
            '  echo "Regenerate the wrapper from the intended environment, or edit the script to activate it before launching." >&2',
            '  exit $rc',
            'fi',
            "",
        ]
    )


def build_claude_stdio_example(script_path: Path, *, ssh_host: str) -> str:
    """Build a concise Claude Code stdio configuration example."""
    return "\n".join(
        [
            "Claude Code example:",
            "",
            "claude mcp add --scope user --transport stdio frpdeck -- \\",
            f"  ssh {ssh_host} {script_path}",
        ]
    )


def build_install_summary(script_path: Path, *, instance_dir: Path, python_executable: Path) -> str:
    """Build a concise install summary for wrapper creation."""
    return "\n".join(
        [
            f"Wrapper path: {script_path}",
            f"Bound instance: {instance_dir}",
            f"Python: {python_executable}",
            "Please manually verify the SSH command first before enabling BatchMode yes.",
            "If this wrapper fails remotely, verify that the embedded Python interpreter is valid in that environment.",
            "For uv or virtualenv-managed setups, regenerate the wrapper from the intended environment or activate it before launching.",
        ]
    )


def _detect_safe_workdir(fallback: Path) -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return fallback


def resolve_wrapper_python_executable(python_override: Path | None = None) -> Path:
    """Resolve the Python interpreter embedded into the wrapper script."""
    if python_override is not None:
        return python_override.resolve()
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        candidate = Path(virtual_env).expanduser().resolve() / "bin" / "python"
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return Path(sys.executable).resolve()


def _wrapper_state(script_path: Path, *, instance_dir: Path, python_executable: Path | None = None) -> dict[str, Any]:
    return {
        "exists": script_path.exists(),
        "wrapper_path": script_path,
        "instance_dir": instance_dir,
        "python": python_executable,
    }


def _record_wrapper_audit(
    instance_dir: Path,
    *,
    operation: str,
    target: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    result: dict[str, Any],
) -> str | None:
    try:
        record_audit_event(
            instance_dir,
            operation=operation,
            target=target,
            before=before,
            after=after,
            result=result,
            actor=build_actor(source="cli"),
        )
    except Exception as exc:
        return f"audit log append failed: {exc}"
    return None


@mcp_app.command("install-stdio-wrapper")
def install_stdio_wrapper_command(
    instance: Path = typer.Option(Path("."), "--instance", exists=True, file_okay=False, dir_okay=True, help="Instance directory"),
    python_path: Path | None = typer.Option(None, "--python", exists=True, file_okay=True, dir_okay=False, resolve_path=True, help="Python interpreter to embed in the wrapper script"),
    ssh_host: str = typer.Option(DEFAULT_SSH_HOST, "--ssh-host", help="Host shown in the Claude Code example command"),
) -> None:
    """Install or update a bound stdio MCP wrapper script for one instance."""
    instance_dir = instance.resolve()
    script_path = instance_dir / WRAPPER_FILENAME
    workdir = _detect_safe_workdir(instance_dir)
    python_executable = resolve_wrapper_python_executable(python_path)
    with instance_lock(instance_dir / "state" / ".frpdeck.lock"):
        before = _wrapper_state(script_path, instance_dir=instance_dir)
        content = render_stdio_wrapper(instance_dir, python_executable=python_executable, workdir=workdir)
        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(0o755)
        after = _wrapper_state(script_path, instance_dir=instance_dir, python_executable=python_executable)
        warning = _record_wrapper_audit(
            instance_dir,
            operation="mcp_wrapper_install",
            target={"wrapper_path": script_path, "instance_dir": instance_dir},
            before=before,
            after=after,
            result={"ok": True, "error_code": None, "errors": [], "warnings": []},
        )

    typer.echo(f"{'Updated' if before['exists'] else 'Installed'} stdio wrapper.")
    typer.echo(build_install_summary(script_path, instance_dir=instance_dir, python_executable=python_executable))
    typer.echo(build_claude_stdio_example(script_path, ssh_host=ssh_host))
    if warning is not None:
        typer.echo(f"WARNING: {warning}")


@mcp_app.command("uninstall-stdio-wrapper")
def uninstall_stdio_wrapper_command(
    instance: Path = typer.Option(Path("."), "--instance", exists=True, file_okay=False, dir_okay=True, help="Instance directory"),
) -> None:
    """Remove the bound stdio MCP wrapper script for one instance."""
    instance_dir = instance.resolve()
    script_path = instance_dir / WRAPPER_FILENAME
    with instance_lock(instance_dir / "state" / ".frpdeck.lock"):
        before = _wrapper_state(script_path, instance_dir=instance_dir)
        if not script_path.exists():
            warning = _record_wrapper_audit(
                instance_dir,
                operation="mcp_wrapper_uninstall",
                target={"wrapper_path": script_path, "instance_dir": instance_dir},
                before=before,
                after=_wrapper_state(script_path, instance_dir=instance_dir),
                result={"ok": True, "error_code": None, "errors": [], "warnings": []},
            )
            typer.echo(f"Stdio wrapper already absent: {script_path}")
            if warning is not None:
                typer.echo(f"WARNING: {warning}")
            return
        script_path.unlink()
        warning = _record_wrapper_audit(
            instance_dir,
            operation="mcp_wrapper_uninstall",
            target={"wrapper_path": script_path, "instance_dir": instance_dir},
            before=before,
            after=_wrapper_state(script_path, instance_dir=instance_dir),
            result={"ok": True, "error_code": None, "errors": [], "warnings": []},
        )
    typer.echo(f"Removed stdio wrapper: {script_path}")
    if warning is not None:
        typer.echo(f"WARNING: {warning}")