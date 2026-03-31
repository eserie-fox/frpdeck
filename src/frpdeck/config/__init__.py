"""Instance configuration helpers."""

from frpdeck.config.instance import (
    PROXY_FILE_DEFAULTS_RESOURCE_SPEC,
    SCAFFOLD_CLIENT_OVERRIDES_RESOURCE_SPEC,
    SCAFFOLD_INSTANCE_LAYOUT_RESOURCE_SPEC,
    SCAFFOLD_PROXY_FILE_OVERRIDES_RESOURCE_SPEC,
    SCAFFOLD_SERVER_OVERRIDES_RESOURCE_SPEC,
    SCAFFOLD_TOKEN_EXAMPLE_RESOURCE_SPEC,
    ScaffoldInstanceLayout,
    load_node_defaults,
    load_proxy_file_defaults,
    load_scaffold_instance_layout,
    load_scaffold_node_overrides,
    load_scaffold_proxy_file_overrides,
    load_scaffold_token_example,
    merge_node_mapping,
    merge_proxy_file_mapping,
    validate_node_mapping,
    validate_proxy_file_mapping,
)
from frpdeck.config.merge import config_deep_merge

__all__ = [
    "PROXY_FILE_DEFAULTS_RESOURCE_SPEC",
    "SCAFFOLD_CLIENT_OVERRIDES_RESOURCE_SPEC",
    "SCAFFOLD_INSTANCE_LAYOUT_RESOURCE_SPEC",
    "SCAFFOLD_PROXY_FILE_OVERRIDES_RESOURCE_SPEC",
    "SCAFFOLD_SERVER_OVERRIDES_RESOURCE_SPEC",
    "SCAFFOLD_TOKEN_EXAMPLE_RESOURCE_SPEC",
    "ScaffoldInstanceLayout",
    "config_deep_merge",
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
