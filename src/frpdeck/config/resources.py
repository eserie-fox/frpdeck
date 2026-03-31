"""Minimal resource loading helpers for package-shipped JSON defaults."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any


_PKG_SCHEME = "pkg://"


def read_text(spec: str | Path, *, encoding: str = "utf-8") -> str:
    """Read text from a filesystem path or ``pkg://`` resource spec."""

    if isinstance(spec, Path):
        return spec.read_text(encoding=encoding)

    text = str(spec)
    if not text.startswith(_PKG_SCHEME):
        return Path(text).expanduser().read_text(encoding=encoding)

    payload = text[len(_PKG_SCHEME) :]
    parts = [part for part in payload.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"invalid package resource spec: {spec}")

    package = parts[0]
    resource_parts = parts[1:]
    return resources.files(package).joinpath(*resource_parts).read_text(encoding=encoding)


def read_json(spec: str | Path) -> Any:
    """Read a JSON resource from disk or package resources."""

    return json.loads(read_text(spec))


def read_json_mapping(spec: str | Path) -> dict[str, Any]:
    """Read and validate a JSON object resource."""

    payload = read_json(spec)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON resource root must be an object: {spec}")
    return payload


__all__ = ["read_json", "read_json_mapping", "read_text"]
