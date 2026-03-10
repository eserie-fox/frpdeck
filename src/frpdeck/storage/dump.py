"""YAML and JSON serialization helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


def dump_yaml_model(model: BaseModel, path: Path) -> None:
    """Write a pydantic model to YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(model.model_dump(mode="json", exclude_none=True), handle, sort_keys=False)


def dump_yaml_data(data: dict[str, Any], path: Path) -> None:
    """Write arbitrary data to YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def dump_json_data(data: dict[str, Any], path: Path) -> None:
    """Write JSON data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
