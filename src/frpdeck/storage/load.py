"""Load instance configuration from disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from frpdeck.config.instance import validate_node_mapping, validate_proxy_file_mapping
from frpdeck.domain.errors import ConfigLoadError
from frpdeck.domain.proxy import ProxyFile
from frpdeck.domain.state import NodeConfig


def load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file from disk."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise ConfigLoadError(f"config file not found: {path}") from exc
    except OSError as exc:
        raise ConfigLoadError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigLoadError(f"expected mapping in {path}")
    return data


def load_node_config(instance_dir: Path) -> NodeConfig:
    """Load node.yaml from an instance directory."""
    payload = load_yaml_file(instance_dir / "node.yaml")
    try:
        return validate_node_mapping(payload)
    except Exception as exc:
        raise ConfigLoadError(f"invalid node config: {exc}") from exc


def load_proxy_file(instance_dir: Path) -> ProxyFile:
    """Load proxies.yaml if present, otherwise return an empty proxy list."""
    path = instance_dir / "proxies.yaml"
    payload = {} if not path.exists() else load_yaml_file(path)
    try:
        return validate_proxy_file_mapping(payload)
    except Exception as exc:
        raise ConfigLoadError(f"invalid proxy config: {exc}") from exc
