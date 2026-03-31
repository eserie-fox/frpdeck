from __future__ import annotations

from typing import Any, Mapping

from frpdeck.config import config_deep_merge, load_node_defaults, validate_node_mapping
from frpdeck.domain.enums import Role
from frpdeck.domain.install import BinaryConfig


def build_client_node(
    *,
    instance_name: str = "client-demo",
    service_name: str = "client-demo-frpc",
    server_addr: str = "example.com",
    auth: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
):
    payload: dict[str, Any] = {
        "instance_name": instance_name,
        "role": "client",
        "service": {"service_name": service_name},
        "client": {
            "server_addr": server_addr,
            "auth": dict(auth or {"method": "token", "token": "secret"}),
        },
    }
    if overrides:
        payload = config_deep_merge(payload, overrides)
    return validate_node_mapping(payload)


def build_server_node(
    *,
    instance_name: str = "server-demo",
    service_name: str = "server-demo-frps",
    auth: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
):
    payload: dict[str, Any] = {
        "instance_name": instance_name,
        "role": "server",
        "service": {"service_name": service_name},
        "server": {
            "auth": dict(auth or {"method": "token", "token": "secret"}),
        },
    }
    if overrides:
        payload = config_deep_merge(payload, overrides)
    return validate_node_mapping(payload)


def build_binary_config(*, overrides: Mapping[str, Any] | None = None) -> BinaryConfig:
    payload = load_node_defaults(Role.CLIENT)["binary"]
    if overrides:
        payload = config_deep_merge(payload, overrides)
    return BinaryConfig.model_validate(payload)
