"""Create new instance directories and starter configs."""

from __future__ import annotations

from pathlib import Path

from frpdeck.config import (
    config_deep_merge,
    load_node_defaults,
    load_proxy_file_defaults,
    load_scaffold_instance_layout,
    load_scaffold_node_overrides,
    load_scaffold_proxy_file_overrides,
    load_scaffold_token_example,
)
from frpdeck.domain.enums import Role
from frpdeck.domain.proxy import ProxyFile
from frpdeck.domain.state import NODE_CONFIG_ADAPTER
from frpdeck.storage.dump import dump_yaml_model


def scaffold_instance(base_dir: Path, role: Role, instance_name: str) -> Path:
    """Create an instance directory with starter files."""
    instance_dir = (base_dir / instance_name).resolve()
    instance_dir.mkdir(parents=True, exist_ok=False)
    for relative in load_scaffold_instance_layout().directories_for_role(role):
        (instance_dir / relative).mkdir(parents=True, exist_ok=True)

    service_suffix = "frpc" if role == Role.CLIENT else "frps"
    service_name = f"frpdeck-{instance_name}-{service_suffix}"
    node_defaults = load_node_defaults(role)
    node_scaffold_overrides = load_scaffold_node_overrides(role)
    node_payload = config_deep_merge(
        config_deep_merge(node_defaults, node_scaffold_overrides),
        {
            "instance_name": instance_name,
            "role": role.value,
            "service": {"service_name": service_name},
        },
    )
    if role == Role.CLIENT:
        node_payload = config_deep_merge(node_payload, {"client": {"user": instance_name}})
    node = NODE_CONFIG_ADAPTER.validate_python(node_payload)
    dump_yaml_model(node, instance_dir / "node.yaml")

    if role == Role.CLIENT:
        proxies = ProxyFile.model_validate(
            config_deep_merge(
                load_proxy_file_defaults(),
                load_scaffold_proxy_file_overrides(),
            )
        )
        dump_yaml_model(proxies, instance_dir / "proxies.yaml")

    (instance_dir / "secrets" / "token.txt.example").write_text(load_scaffold_token_example(), encoding="utf-8")
    return instance_dir
