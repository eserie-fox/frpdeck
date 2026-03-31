from pathlib import Path

import pytest
from pydantic import ValidationError

from frpdeck.config import validate_node_mapping
from frpdeck.domain.enums import FrpLogLevel, FrpdeckLogLevel, Role
from frpdeck.domain.client_config import AuthConfig
from frpdeck.domain.proxy import HttpProxyConfig, PROXY_ADAPTER, TcpProxyConfig
from frpdeck.domain.versioning import compare_versions, normalize_version
from tests.support import build_binary_config, build_client_node


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

    client = validate_node_mapping(client_payload)
    server = validate_node_mapping(server_payload)

    assert client.role == Role.CLIENT
    assert server.role == Role.SERVER
    assert client.frpdeck_logging.stream == "stderr"
    assert client.frpdeck_logging.level == FrpdeckLogLevel.INFO


def test_frpdeck_logging_stream_allows_fixed_values_only() -> None:
    for stream in ["stdout", "stderr", "none"]:
        node = build_client_node(overrides={"frpdeck_logging": {"stream": stream}})
        assert node.frpdeck_logging.stream == stream

    with pytest.raises(ValidationError):
        build_client_node(overrides={"frpdeck_logging": {"stream": "default"}})


def test_frpdeck_log_level_is_constrained() -> None:
    node = build_client_node(overrides={"frpdeck_logging": {"level": "DEBUG"}})

    assert node.frpdeck_logging.level == FrpdeckLogLevel.DEBUG

    with pytest.raises(ValidationError):
        build_client_node(overrides={"frpdeck_logging": {"level": "WARN"}})


def test_frp_log_level_is_constrained() -> None:
    node = build_client_node(overrides={"client": {"log": {"level": "trace"}}})

    assert node.client.log.level == FrpLogLevel.TRACE

    with pytest.raises(ValidationError):
        build_client_node(overrides={"client": {"log": {"level": "verbose"}}})


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
    auth = AuthConfig(method="token", token_file=Path("secrets/token.txt"))
    assert auth.token_file == Path("secrets/token.txt")
    assert auth.method == "token"

    with pytest.raises(ValueError):
        AuthConfig(method="token", token="inline", token_file=Path("secrets/token.txt"))


def test_binary_version_and_version_comparison_normalization() -> None:
    binary = build_binary_config(overrides={"version": "v0.65.0"})

    assert binary.version == "0.65.0"
    assert normalize_version("v0.65.0") == "0.65.0"
    assert compare_versions("0.65.0", "0.9.0") == 1
    assert compare_versions("0.65.0", "0.67.0") == -1
    assert compare_versions("v0.65.0", "0.65.0") == 0
