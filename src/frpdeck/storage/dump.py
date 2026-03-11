"""YAML and JSON serialization helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

import yaml
from pydantic import BaseModel


def dump_yaml_model(model: BaseModel, path: Path) -> None:
    """Write a pydantic model to YAML."""
    _atomic_write_text(
        path,
        yaml.safe_dump(model.model_dump(mode="json", exclude_none=True), sort_keys=False),
    )


def dump_yaml_data(data: dict[str, Any], path: Path) -> None:
    """Write arbitrary data to YAML."""
    _atomic_write_text(path, yaml.safe_dump(data, sort_keys=False))


def dump_json_data(data: dict[str, Any], path: Path) -> None:
    """Write JSON data."""
    _atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True))


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via a temporary file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
