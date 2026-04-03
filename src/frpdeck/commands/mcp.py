"""MCP helper commands for stdio wrapper installation."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

import typer

from frpdeck.commands._invocation import build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges
from frpdeck.domain.errors import PermissionOperationError
from frpdeck.services.privilege import can_delete_path, can_write_file, root_owned_hint
from frpdeck.services.audit import build_actor, record_audit_event
from frpdeck.storage.file_lock import instance_lock
from frpdeck.storage.load import load_node_config


WRAPPER_FILENAME = "start-mcp-stdio.sh"
DEFAULT_SSH_HOST = "grape_networking"

mcp_app = typer.Typer(help="MCP stdio helper commands", no_args_is_help=True)


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
            instance_name=_instance_name(instance_dir),
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
    ctx: typer.Context,
    instance: Path = typer.Option(Path("."), "--instance", exists=True, file_okay=False, dir_okay=True, help="Instance directory"),
    python_path: Path | None = typer.Option(
        None,
        "--python",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Python interpreter to embed in the wrapper script. Defaults to the current frpdeck interpreter.",
    ),
    ssh_host: str = typer.Option(DEFAULT_SSH_HOST, "--ssh-host", help="Host shown in the Claude Code example command"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Install or update a bound stdio MCP wrapper script for one instance."""
    instance_dir = instance.resolve()
    script_path = instance_dir / WRAPPER_FILENAME
    workdir = _detect_safe_workdir(instance_dir)
    python_executable = resolve_wrapper_python_executable(python_path)
    invocation = build_command_invocation(
        ctx,
        overrides={
            "instance": instance_dir,
            "python_path": python_path.resolve() if python_path is not None else None,
        },
    )
    try:
        if maybe_reexec_with_sudo(
            operation="mcp install-stdio-wrapper",
            sudo_requested=sudo,
            invocation=invocation,
        ):
            return
        raise_for_missing_privileges(
            operation="mcp install-stdio-wrapper",
            reasons=_analyze_wrapper_root_requirements(instance_dir, uninstall=False),
            invocation=invocation,
        )
        with instance_lock(instance_dir / "state" / ".frpdeck.lock"):
            before = _wrapper_state(script_path, instance_dir=instance_dir)
            content = render_stdio_wrapper(instance_dir, python_executable=python_executable, workdir=workdir)
            _write_wrapper_script(script_path, content)
            after = _wrapper_state(script_path, instance_dir=instance_dir, python_executable=python_executable)
            warning = _record_wrapper_audit(
                instance_dir,
                operation="mcp_wrapper_install",
                target={"wrapper_path": script_path, "instance_dir": instance_dir},
                before=before,
                after=after,
                result={"ok": True, "error_code": None, "errors": [], "warnings": []},
            )
    except PermissionOperationError as exc:
        typer.echo(f"ERROR: {exc}")
        raise typer.Exit(code=1) from exc

    typer.echo(f"{'Updated' if before['exists'] else 'Installed'} stdio wrapper.")
    typer.echo(build_install_summary(script_path, instance_dir=instance_dir, python_executable=python_executable))
    typer.echo(build_claude_stdio_example(script_path, ssh_host=ssh_host))
    if warning is not None:
        typer.echo(f"WARNING: {warning}")


@mcp_app.command("uninstall-stdio-wrapper")
def uninstall_stdio_wrapper_command(
    ctx: typer.Context,
    instance: Path = typer.Option(Path("."), "--instance", exists=True, file_okay=False, dir_okay=True, help="Instance directory"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Remove the bound stdio MCP wrapper script for one instance."""
    instance_dir = instance.resolve()
    script_path = instance_dir / WRAPPER_FILENAME
    invocation = build_command_invocation(ctx, overrides={"instance": instance_dir})
    try:
        if maybe_reexec_with_sudo(
            operation="mcp uninstall-stdio-wrapper",
            sudo_requested=sudo,
            invocation=invocation,
        ):
            return
        raise_for_missing_privileges(
            operation="mcp uninstall-stdio-wrapper",
            reasons=_analyze_wrapper_root_requirements(instance_dir, uninstall=True),
            invocation=invocation,
        )
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
            _remove_wrapper_script(script_path)
            warning = _record_wrapper_audit(
                instance_dir,
                operation="mcp_wrapper_uninstall",
                target={"wrapper_path": script_path, "instance_dir": instance_dir},
                before=before,
                after=_wrapper_state(script_path, instance_dir=instance_dir),
                result={"ok": True, "error_code": None, "errors": [], "warnings": []},
            )
    except PermissionOperationError as exc:
        typer.echo(f"ERROR: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(f"Removed stdio wrapper: {script_path}")
    if warning is not None:
        typer.echo(f"WARNING: {warning}")


def _instance_name(instance_dir: Path) -> str | None:
    try:
        return load_node_config(instance_dir).instance_name
    except Exception:
        return None


def _analyze_wrapper_root_requirements(instance_dir: Path, *, uninstall: bool) -> list[str]:
    lock_path = instance_dir.resolve() / "state" / ".frpdeck.lock"
    script_path = instance_dir.resolve() / WRAPPER_FILENAME
    reasons: list[str] = []

    if not can_write_file(lock_path):
        reasons.append(f"instance lock path is not writable by current user: {lock_path}{root_owned_hint(lock_path)}")

    if uninstall:
        if script_path.exists() and not can_delete_path(script_path):
            reasons.append(f"wrapper path is not removable by current user: {script_path}{root_owned_hint(script_path)}")
    elif not can_write_file(script_path):
        reasons.append(f"wrapper path is not writable by current user: {script_path}{root_owned_hint(script_path)}")

    return reasons


def _write_wrapper_script(script_path: Path, content: str) -> None:
    try:
        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(0o755)
    except PermissionError as exc:
        raise PermissionOperationError(
            f"cannot update stdio wrapper at {script_path}; use sudo or adjust configured paths"
        ) from exc


def _remove_wrapper_script(script_path: Path) -> None:
    try:
        script_path.unlink()
    except PermissionError as exc:
        raise PermissionOperationError(
            f"cannot remove stdio wrapper at {script_path}; use sudo or adjust configured paths"
        ) from exc
