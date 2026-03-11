"""Read-only audit inspection commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from frpdeck.commands.output import emit_json_envelope
from frpdeck.services.audit import audit_log_path, read_recent_audit_entries


audit_app = typer.Typer(help="Read-only audit inspection")


def register(app: typer.Typer) -> None:
    app.add_typer(audit_app, name="audit")


@audit_app.command("recent")
def recent_command(
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum number of recent entries to display"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show the most recent write audit entries for one instance."""
    instance_dir = instance.resolve()
    entries = read_recent_audit_entries(instance_dir, limit=limit)

    if json_output:
        emit_json_envelope(
            command="audit recent",
            instance=instance_dir,
            ok=True,
            data={"count": len(entries), "entries": entries},
            errors=[],
            warnings=[],
        )
        return

    if not entries:
        if audit_log_path(instance_dir).exists():
            typer.echo("no audit entries found")
        else:
            typer.echo("no audit log found")
        return

    for entry in entries:
        typer.echo(_format_entry(entry))


def _format_entry(entry: dict[str, Any]) -> str:
    ts = str(entry.get("ts") or "-")
    operation = str(entry.get("operation") or "-")
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    actor = entry.get("actor") if isinstance(entry.get("actor"), dict) else {}
    status = "ok" if result.get("ok", False) else "failed"
    source = actor.get("source") or "unknown"
    target_text = _target_summary(entry.get("target") if isinstance(entry.get("target"), dict) else {})
    return f"{ts}  {operation:<20}  {status:<6}  source={source}  {target_text}".rstrip()


def _target_summary(target: dict[str, Any]) -> str:
    if "proxy_name" in target:
        suffix = ""
        if "remove_mode" in target:
            suffix = f" mode={target['remove_mode']}"
        return f"proxy={target['proxy_name']}{suffix}"
    if "wrapper_path" in target:
        return f"wrapper={Path(str(target['wrapper_path'])).name}"
    if "reload_requested" in target:
        return f"reload={str(target['reload_requested']).lower()}"
    return "target=-"