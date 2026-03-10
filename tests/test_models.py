from pathlib import Path

import pytest

from frpdeck.domain.client_config import AuthConfig
from frpdeck.domain.install import BinaryConfig
from frpdeck.domain.proxy import HttpProxyConfig, PROXY_ADAPTER, TcpProxyConfig
from frpdeck.domain.state import NODE_CONFIG_ADAPTER
from frpdeck.domain.versioning import compare_versions, normalize_version


def test_client_and_server_models_load() -> None:
    client_payload = {
        "instance_name": "demo-client",
        "role": "client",
        "service": {"service_name": "demo-frpc"},
        "client": {
            "server_addr": "example.com",
            "server_port": 7000,
            "auth": {"token": "secret"},
        },
    }
    server_payload = {
        "instance_name": "demo-server",
        "role": "server",
        "service": {"service_name": "demo-frps"},
        "server": {
            "bind_addr": "0.0.0.0",
            "bind_port": 7000,
            "auth": {"token": "secret"},
        },
    }

    client = NODE_CONFIG_ADAPTER.validate_python(client_payload)
    server = NODE_CONFIG_ADAPTER.validate_python(server_payload)

    assert client.role.value == "client"
    assert server.role.value == "server"


def test_proxy_discriminated_union() -> None:
    tcp = PROXY_ADAPTER.validate_python(
        {"name": "ssh", "type": "tcp", "local_port": 22, "remote_port": 6000}
    )
    http = PROXY_ADAPTER.validate_python(
        {"name": "web", "type": "http", "local_port": 8080, "custom_domains": ["example.com"]}
    )

    assert isinstance(tcp, TcpProxyConfig)
    assert isinstance(http, HttpProxyConfig)


def test_auth_token_and_token_file_rules() -> None:
    auth = AuthConfig(token_file=Path("secrets/token.txt"))
    assert auth.token_file == Path("secrets/token.txt")
    assert auth.method == "token"

    with pytest.raises(ValueError):
        AuthConfig(token="inline", token_file=Path("secrets/token.txt"))


def test_binary_version_and_version_comparison_normalization() -> None:
    binary = BinaryConfig(version="v0.65.0")

    assert binary.version == "0.65.0"
    assert normalize_version("v0.65.0") == "0.65.0"
    assert compare_versions("0.65.0", "0.9.0") == 1
    assert compare_versions("0.65.0", "0.67.0") == -1
    assert compare_versions("v0.65.0", "0.65.0") == 0
