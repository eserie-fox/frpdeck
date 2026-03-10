"""Validation logic that goes beyond schema parsing."""

from __future__ import annotations

from pathlib import Path

from frpdeck.domain.enums import ProxyType, Role
from frpdeck.domain.proxy import HttpProxyConfig, HttpsProxyConfig, ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.state import ClientNodeConfig, NodeBase, ServerNodeConfig
from frpdeck.domain.paths import resolve_path_from_instance


PLACEHOLDER_PREFIX = "PLEASE_FILL_"


def validate_instance(instance_dir: Path, node: NodeBase, proxy_file: ProxyFile | None = None) -> list[str]:
    """Return human-readable validation errors."""
    errors: list[str] = []
    proxy_file = proxy_file or ProxyFile()

    try:
        node.resolved_paths(instance_dir)
    except Exception as exc:
        errors.append(f"path resolution failed: {exc}")

    if node.role == Role.CLIENT:
        assert isinstance(node, ClientNodeConfig)
        if _is_placeholder(node.client.server_addr):
            errors.append("client.server_addr still uses a placeholder value")
        _validate_auth(instance_dir, node.client.auth.token, node.client.auth.token_file, errors, "client.auth")
        _validate_proxy_file(proxy_file, errors)
    else:
        assert isinstance(node, ServerNodeConfig)
        if node.server.subdomain_host and _is_placeholder(node.server.subdomain_host):
            errors.append("server.subdomain_host still uses a placeholder value")
        _validate_auth(instance_dir, node.server.auth.token, node.server.auth.token_file, errors, "server.auth")

    return errors


def _validate_auth(
    instance_dir: Path,
    token: str | None,
    token_file: Path | None,
    errors: list[str],
    scope: str,
) -> None:
    if not token and not token_file:
        errors.append(f"{scope} requires either token or token_file")
        return
    if token and _is_placeholder(token):
        errors.append(f"{scope}.token still uses a placeholder value")
    if token_file:
        resolved = resolve_path_from_instance(token_file, instance_dir)
        if not resolved.exists():
            errors.append(f"{scope}.token_file does not exist: {resolved}")
            return
        content = resolved.read_text(encoding="utf-8").strip()
        if not content:
            errors.append(f"{scope}.token_file is empty: {resolved}")
        elif _is_placeholder(content):
            errors.append(f"{scope}.token_file still contains a placeholder value: {resolved}")


def _validate_proxy_file(proxy_file: ProxyFile, errors: list[str]) -> None:
    seen_names: set[str] = set()
    used_remote_ports: dict[ProxyType, set[int]] = {ProxyType.TCP: set(), ProxyType.UDP: set()}

    for proxy in proxy_file.proxies:
        if proxy.name in seen_names:
            errors.append(f"duplicate proxy name: {proxy.name}")
        seen_names.add(proxy.name)
        if not proxy.enabled:
            continue
        if isinstance(proxy, (TcpProxyConfig, UdpProxyConfig)):
            ports = used_remote_ports[proxy.type]
            if proxy.remote_port in ports:
                errors.append(f"duplicate {proxy.type.value} remote_port: {proxy.remote_port}")
            ports.add(proxy.remote_port)
        if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)) and not proxy.custom_domains and not proxy.subdomain:
            errors.append(f"proxy {proxy.name} requires custom_domains or subdomain")


def _is_placeholder(value: str) -> bool:
    return value.startswith(PLACEHOLDER_PREFIX)
