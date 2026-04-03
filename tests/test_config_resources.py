from pathlib import Path
import tomllib

from frpdeck.config import (
    load_node_defaults,
    load_proxy_file_defaults,
    load_scaffold_instance_layout,
    load_scaffold_node_overrides,
    load_scaffold_proxy_file_overrides,
    load_scaffold_token_example,
)
from frpdeck.domain.enums import Role


def test_config_default_resources_are_readable_via_package_loaders() -> None:
    client_defaults = load_node_defaults(Role.CLIENT)
    server_defaults = load_node_defaults(Role.SERVER)
    client_overrides = load_scaffold_node_overrides(Role.CLIENT)
    server_overrides = load_scaffold_node_overrides(Role.SERVER)
    proxy_defaults = load_proxy_file_defaults()
    proxy_overrides = load_scaffold_proxy_file_overrides()
    layout = load_scaffold_instance_layout()
    token_example = load_scaffold_token_example()

    assert client_defaults["frpdeck_logging"]["stream"] == "stderr"
    assert client_defaults["client"]["log"]["level"] == "info"
    assert server_defaults["server"]["vhost_http_port"] is None
    assert server_defaults["server"]["vhost_https_port"] is None
    assert client_overrides["client"]["server_addr"] == "PLEASE_FILL_SERVER_ADDR"
    assert client_overrides["client"]["auth"]["token_file"] == "secrets/token.txt"
    assert "subdomain_host" not in server_overrides["server"]
    assert server_overrides["server"]["auth"]["token_file"] == "secrets/token.txt"
    assert proxy_defaults == {"proxies": []}
    assert proxy_overrides["proxies"][0]["name"] == "sample_http"
    assert proxy_overrides["proxies"][0]["type"] == "http"
    assert "rendered/proxies.d" in layout.common_directories
    assert "secrets" in layout.common_directories
    assert layout.directories_for_role(Role.CLIENT) == layout.common_directories
    assert token_example == "PLEASE_FILL_TOKEN\n"


def test_pyproject_package_data_includes_config_default_json_resources() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["frpdeck"]

    assert "templates/**/*.j2" in package_data
    assert "config_defaults/**/*.json" in package_data
