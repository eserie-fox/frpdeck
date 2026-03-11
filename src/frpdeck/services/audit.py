"""Append-only audit logging and proxy revision snapshots."""

from __future__ import annotations

import getpass
import json
import os
import socket
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

import yaml
from pydantic import BaseModel


_AUDIT_ACTOR_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("frpdeck_audit_actor_context", default={})


def utc_timestamp() -> str:
    """Return an ISO 8601 UTC timestamp for audit events."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_event_id() -> str:
    """Return a stable unique identifier for one audit event."""
    return uuid.uuid4().hex


@contextmanager
def audit_actor(source: str, **extra: Any) -> Iterator[None]:
    """Temporarily set audit actor context for one call chain."""
    current = dict(_AUDIT_ACTOR_CONTEXT.get())
    current.update({"source": source, **extra})
    token = _AUDIT_ACTOR_CONTEXT.set(current)
    try:
        yield
    finally:
        _AUDIT_ACTOR_CONTEXT.reset(token)


def build_actor(source: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build stable actor metadata for audit records."""
    payload = dict(_AUDIT_ACTOR_CONTEXT.get())
    payload.update(extra)
    try:
        user = getpass.getuser()
    except Exception:
        user = None
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = None
    actor = {
        "source": source or payload.pop("source", "cli"),
        "user": user,
        "hostname": hostname,
        "pid": os.getpid(),
    }
    for key, value in payload.items():
        if value is not None:
            actor[key] = json_ready(value)
    return actor


def audit_log_path(instance_dir: Path) -> Path:
    """Return the append-only audit log path for one instance."""
    return instance_dir / "state" / "audit" / "audit.jsonl"


def read_recent_audit_entries(instance_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent audit entries in reverse chronological order."""
    if limit <= 0:
        return []
    path = audit_log_path(instance_dir.resolve())
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    recent_lines = lines[-limit:]
    entries = [json.loads(line) for line in recent_lines]
    entries.reverse()
    return entries


def revision_dir_path(instance_dir: Path, *, ts: str, operation: str, event_id: str) -> Path:
    """Return the revision snapshot directory for one event."""
    safe_ts = ts.replace("-", "").replace(":", "").replace("+", "").replace(".", "").replace("Z", "Z")
    return instance_dir / "state" / "revisions" / f"{safe_ts}-{operation}-{event_id}"


def json_ready(value: Any) -> Any:
    """Convert supported objects into stable JSON/YAML-safe data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return json_ready(value.model_dump(mode="json", exclude_none=False))
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    raise TypeError(f"unsupported audit serialization type: {type(value).__name__}")


def yaml_text(value: Any) -> str:
    """Serialize one object into stable YAML text."""
    return yaml.safe_dump(json_ready(value), sort_keys=False)


def read_text_snapshot(path: Path, *, fallback: Any | None = None) -> str | None:
    """Read text from disk, or serialize fallback data when the file is absent."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    if fallback is None:
        return None
    return yaml_text(fallback)


def record_audit_event(
    instance_dir: Path,
    *,
    operation: str,
    target: Any,
    before: Any,
    after: Any,
    result: dict[str, Any],
    actor: dict[str, Any] | None = None,
    ts: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Append one JSONL audit record and return the written payload."""
    instance = instance_dir.resolve()
    payload = {
        "ts": ts or utc_timestamp(),
        "event_id": event_id or new_event_id(),
        "operation": operation,
        "instance_dir": str(instance),
        "actor": actor or build_actor(),
        "target": json_ready(target),
        "before": json_ready(before),
        "after": json_ready(after),
        "result": json_ready(result),
    }
    path = audit_log_path(instance)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
    return payload


def write_proxy_revision(
    instance_dir: Path,
    *,
    ts: str,
    event_id: str,
    operation: str,
    actor: dict[str, Any],
    result: dict[str, Any],
    before_yaml: str | None,
    after_yaml: str | None,
) -> Path:
    """Write before/after proxy YAML snapshots and event metadata."""
    revision_dir = revision_dir_path(instance_dir.resolve(), ts=ts, operation=operation, event_id=event_id)
    revision_dir.mkdir(parents=True, exist_ok=True)
    if before_yaml is not None:
        (revision_dir / "proxies.before.yaml").write_text(before_yaml, encoding="utf-8")
    if after_yaml is not None:
        (revision_dir / "proxies.after.yaml").write_text(after_yaml, encoding="utf-8")
    meta = {
        "event_id": event_id,
        "operation": operation,
        "ts": ts,
        "instance_dir": str(instance_dir.resolve()),
        "actor": json_ready(actor),
        "result": json_ready(result),
        "before_exists": before_yaml is not None,
        "after_exists": after_yaml is not None,
    }
    (revision_dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return revision_dir