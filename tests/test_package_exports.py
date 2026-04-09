from __future__ import annotations

from importlib import import_module


PACKAGE_MODULES = [
    "frpdeck",
    "frpdeck.commands",
    "frpdeck.config",
    "frpdeck.domain",
    "frpdeck.facade",
    "frpdeck.logging",
    "frpdeck.mcp",
    "frpdeck.services",
    "frpdeck.storage",
    "tests",
]

LEGACY_EXPORTS = {
    "frpdeck": ["__version__"],
    "frpdeck.config": [
        "config_deep_merge",
        "load_node_defaults",
        "validate_node_mapping",
    ],
    "frpdeck.facade": ["ProxyFacade"],
    "frpdeck.logging": [
        "ResolvedLoggingConfig",
        "configure_default_logging",
        "instance_logging_context",
    ],
    "frpdeck.mcp": ["create_mcp_server", "main", "mcp"],
}


def test_package_init_modules_only_expose_empty_exports() -> None:
    for module_name in PACKAGE_MODULES:
        module = import_module(module_name)

        assert module.__all__ == []


def test_legacy_package_level_exports_are_not_available() -> None:
    for module_name, symbols in LEGACY_EXPORTS.items():
        module = import_module(module_name)

        for symbol in symbols:
            assert not hasattr(module, symbol)
