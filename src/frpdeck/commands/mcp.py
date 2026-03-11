"""MCP helper commands for stdio wrapper installation."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import typer


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
            "set -euo pipefail",
            f"cd {shlex.quote(str(workdir))}",
            f"exec {shlex.quote(str(python_executable))} -m frpdeck.mcp.server --instance-dir {shlex.quote(str(instance_dir))}",
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


def _detect_safe_workdir(fallback: Path) -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return fallback


@mcp_app.command("install-stdio-wrapper")
def install_stdio_wrapper_command(
    instance: Path = typer.Option(..., "--instance", exists=True, file_okay=False, dir_okay=True, help="Instance directory"),
    ssh_host: str = typer.Option(DEFAULT_SSH_HOST, "--ssh-host", help="Host shown in the Claude Code example command"),
) -> None:
    """Install or update a bound stdio MCP wrapper script for one instance."""
    instance_dir = instance.resolve()
    script_path = instance_dir / WRAPPER_FILENAME
    script_existed = script_path.exists()
    workdir = _detect_safe_workdir(instance_dir)
    content = render_stdio_wrapper(instance_dir, python_executable=Path(sys.executable).resolve(), workdir=workdir)
    script_path.write_text(content, encoding="utf-8")
    script_path.chmod(0o755)

    typer.echo(f"{'Updated' if script_existed else 'Installed'} stdio wrapper: {script_path}")
    typer.echo(build_claude_stdio_example(script_path, ssh_host=ssh_host))


@mcp_app.command("uninstall-stdio-wrapper")
def uninstall_stdio_wrapper_command(
    instance: Path = typer.Option(..., "--instance", exists=True, file_okay=False, dir_okay=True, help="Instance directory"),
) -> None:
    """Remove the bound stdio MCP wrapper script for one instance."""
    instance_dir = instance.resolve()
    script_path = instance_dir / WRAPPER_FILENAME
    if not script_path.exists():
        typer.echo(f"Stdio wrapper already absent: {script_path}")
        return
    script_path.unlink()
    typer.echo(f"Removed stdio wrapper: {script_path}")