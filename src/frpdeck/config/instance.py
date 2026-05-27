"""Defaults-aware instance config helpers."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, field_validator

from frpdeck.config.merge import config_deep_merge
from frpdeck.config.resources import read_json_mapping
from frpdeck.domain.enums import Role
from frpdeck.domain.proxy import ProxyFile
from frpdeck.domain.state import NODE_CONFIG_ADAPTER, NodeConfig


CLIENT_NODE_DEFAULTS_RESOURCE_SPEC = "pkg://frpdeck/config_defaults/node_client.json"
SERVER_NODE_DEFAULTS_RESOURCE_SPEC = "pkg://frpdeck/config_defaults/node_server.json"
PROXY_FILE_DEFAULTS_RESOURCE_SPEC = "pkg://frpdeck/config_defaults/proxy_file.json"
SCAFFOLD_CLIENT_OVERRIDES_RESOURCE_SPEC = "pkg://frpdeck/config_defaults/scaffold_client_overrides.json"
SCAFFOLD_SERVER_OVERRIDES_RESOURCE_SPEC = "pkg://frpdeck/config_defaults/scaffold_server_overrides.json"
SCAFFOLD_PROXY_FILE_OVERRIDES_RESOURCE_SPEC = "pkg://frpdeck/config_defaults/scaffold_proxy_file_overrides.json"
SCAFFOLD_INSTANCE_LAYOUT_RESOURCE_SPEC = "pkg://frpdeck/config_defaults/scaffold_instance_layout.json"
SCAFFOLD_TOKEN_EXAMPLE_RESOURCE_SPEC = "pkg://frpdeck/config_defaults/scaffold_token_example.json"


class ScaffoldInstanceLayout(BaseModel):
    """Directory layout definition for scaffolded instances."""

    model_config = ConfigDict(extra="forbid")

    common_directories: list[str]
    client_directories: list[str]
    server_directories: list[str]

    @field_validator("common_directories", "client_directories", "server_directories")
    @classmethod
    def _validate_directories(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or value.startswith("/") or value in {".", ".."}:
                raise ValueError(f"invalid scaffold directory entry: {value!r}")
        return values

    def directories_for_role(self, role: Role | str) -> list[str]:
        resolved_role = Role(role)
        role_directories = self.client_directories if resolved_role == Role.CLIENT else self.server_directories
        return [*self.common_directories, *role_directories]


def load_node_defaults(role: Role | str) -> dict[str, Any]:
    """Load package-shipped defaults for one node role."""

    resolved_role = Role(role)
    resource_spec = (
        CLIENT_NODE_DEFAULTS_RESOURCE_SPEC if resolved_role == Role.CLIENT else SERVER_NODE_DEFAULTS_RESOURCE_SPEC
    )
    return read_json_mapping(resource_spec)


def load_proxy_file_defaults() -> dict[str, Any]:
    """Load package-shipped defaults for proxies.yaml."""

    return read_json_mapping(PROXY_FILE_DEFAULTS_RESOURCE_SPEC)


def load_scaffold_node_overrides(role: Role | str) -> dict[str, Any]:
    """Load scaffold overrides for one node role."""

    resolved_role = Role(role)
    resource_spec = (
        SCAFFOLD_CLIENT_OVERRIDES_RESOURCE_SPEC
        if resolved_role == Role.CLIENT
        else SCAFFOLD_SERVER_OVERRIDES_RESOURCE_SPEC
    )
    return read_json_mapping(resource_spec)


def load_scaffold_proxy_file_overrides() -> dict[str, Any]:
    """Load scaffold overrides for proxies.yaml."""

    return read_json_mapping(SCAFFOLD_PROXY_FILE_OVERRIDES_RESOURCE_SPEC)


def load_scaffold_instance_layout() -> ScaffoldInstanceLayout:
    """Load the scaffold directory layout definition."""

    return ScaffoldInstanceLayout.model_validate(read_json_mapping(SCAFFOLD_INSTANCE_LAYOUT_RESOURCE_SPEC))


def load_scaffold_token_example() -> str:
    """Load the scaffold token example payload."""

    payload = read_json_mapping(SCAFFOLD_TOKEN_EXAMPLE_RESOURCE_SPEC)
    token_example = payload.get("token_example")
    if not isinstance(token_example, str):
        raise ValueError("scaffold token example must be a string")
    return token_example


def merge_node_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    """Merge role-specific defaults into one raw node mapping."""

    role_value = data.get("role")
    if role_value is None:
        raise ValueError("node config must define role before defaults can be applied")
    return config_deep_merge(load_node_defaults(role_value), dict(data))


def validate_node_mapping(data: Mapping[str, Any]) -> NodeConfig:
    """Merge defaults and validate a node config mapping."""

    return NODE_CONFIG_ADAPTER.validate_python(merge_node_mapping(data))


def merge_proxy_file_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    """Merge defaults into one raw proxy-file mapping."""

    return config_deep_merge(load_proxy_file_defaults(), dict(data))


def validate_proxy_file_mapping(data: Mapping[str, Any]) -> ProxyFile:
    """Merge defaults and validate a proxy-file mapping."""

    return ProxyFile.model_validate(merge_proxy_file_mapping(data))


__all__ = [
    "CLIENT_NODE_DEFAULTS_RESOURCE_SPEC",
    "PROXY_FILE_DEFAULTS_RESOURCE_SPEC",
    "SCAFFOLD_CLIENT_OVERRIDES_RESOURCE_SPEC",
    "SCAFFOLD_INSTANCE_LAYOUT_RESOURCE_SPEC",
    "SCAFFOLD_PROXY_FILE_OVERRIDES_RESOURCE_SPEC",
    "SCAFFOLD_SERVER_OVERRIDES_RESOURCE_SPEC",
    "SCAFFOLD_TOKEN_EXAMPLE_RESOURCE_SPEC",
    "ScaffoldInstanceLayout",
    "SERVER_NODE_DEFAULTS_RESOURCE_SPEC",
    "load_node_defaults",
    "load_proxy_file_defaults",
    "load_scaffold_instance_layout",
    "load_scaffold_node_overrides",
    "load_scaffold_proxy_file_overrides",
    "load_scaffold_token_example",
    "merge_node_mapping",
    "merge_proxy_file_mapping",
    "validate_node_mapping",
    "validate_proxy_file_mapping",
]
