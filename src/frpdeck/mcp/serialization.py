"""Serialization helpers for MCP tools and resources."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def to_jsonable(value: Any) -> Any:
    """Convert supported Python objects into JSON-serializable data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return to_jsonable(value.model_dump(mode="json", exclude_none=False))
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    raise TypeError(f"unsupported MCP serialization type: {type(value).__name__}")


def dump_json(value: Any) -> str:
    """Return stable JSON text for MCP resource content."""
    return json.dumps(to_jsonable(value), ensure_ascii=True, sort_keys=True)


def resolve_instance_dir(instance_dir: str) -> Path:
    """Resolve an instance directory using the existing local-path rules."""
    return Path(instance_dir).expanduser().resolve()