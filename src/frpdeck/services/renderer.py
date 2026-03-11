"""Render FRP and systemd templates into instance artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from frpdeck.domain.client_config import AuthConfig, FrpLogConfig
from frpdeck.domain.enums import Role
from frpdeck.domain.paths import resolve_path_from_instance
from frpdeck.domain.proxy import HttpProxyConfig, HttpsProxyConfig, ProxyConfig, ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.state import ClientNodeConfig, NodeBase, ServerNodeConfig


def _build_environment() -> Environment:
    return Environment(
        loader=PackageLoader("frpdeck"),
        autoescape=select_autoescape(default_for_string=False, disabled_extensions=("j2",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )


ENVIRONMENT = _build_environment()


@dataclass(slots=True)
class RenderSummary:
    main_config_path: Path
    rendered_proxy_paths: list[Path]
    systemd_unit_path: Path


def render_instance(
    instance_dir: Path,
    node: NodeBase,
    proxy_file: ProxyFile | None = None,
    *,
    output_root: Path | None = None,
) -> RenderSummary:
    """Render instance templates into the local rendered directory."""
    rendered_root = output_root or (instance_dir / "rendered")
    proxies_root = rendered_root / "proxies.d"
    systemd_root = rendered_root / "systemd"
    rendered_root.mkdir(parents=True, exist_ok=True)
    proxies_root.mkdir(parents=True, exist_ok=True)
    systemd_root.mkdir(parents=True, exist_ok=True)

    for existing in proxies_root.glob("*.toml"):
        existing.unlink()

    if node.role == Role.CLIENT:
        assert isinstance(node, ClientNodeConfig)
        proxy_file = proxy_file or ProxyFile()
        proxy_paths = _render_client_proxies(instance_dir, proxy_file, proxies_root)
        main_path = rendered_root / "frpc.toml"
        main_content = _render_client_base(instance_dir, node)
        unit_name = "frpc.service.j2"
    else:
        assert isinstance(node, ServerNodeConfig)
        proxy_paths = []
        main_path = rendered_root / "frps.toml"
        main_content = _render_server_base(instance_dir, node)
        unit_name = "frps.service.j2"

    main_path.write_text(main_content, encoding="utf-8")
    unit_path = systemd_root / f"{node.service.service_name}.service"
    unit_path.write_text(_render_systemd(instance_dir, node, unit_name), encoding="utf-8")

    return RenderSummary(main_config_path=main_path, rendered_proxy_paths=proxy_paths, systemd_unit_path=unit_path)


def _render_client_base(instance_dir: Path, node: ClientNodeConfig) -> str:
    template = ENVIRONMENT.get_template("frpc.base.toml.j2")
    paths = node.resolved_paths(instance_dir)
    auth_context = _auth_context(node.client.auth, instance_dir)
    log_context = _log_context(node.client.log, instance_dir)
    context = {
        "user": node.client.user,
        "server_addr": node.client.server_addr,
        "server_port": node.client.server_port,
        "transport_protocol": node.client.transport_protocol.value,
        "web_server": node.client.web_server,
        "login_fail_exit": node.client.login_fail_exit,
        "log": log_context,
        "auth": auth_context,
        "includes_enabled": node.client.includes_enabled,
        "includes_glob": str(paths.proxies_dir() / "*.toml"),
    }
    return template.render(**context)


def _render_server_base(instance_dir: Path, node: ServerNodeConfig) -> str:
    template = ENVIRONMENT.get_template("frps.base.toml.j2")
    context = {
        "bind_addr": node.server.bind_addr,
        "bind_port": node.server.bind_port,
        "kcp_bind_port": node.server.kcp_bind_port,
        "quic_bind_port": node.server.quic_bind_port,
        "vhost_http_port": node.server.vhost_http_port,
        "vhost_https_port": node.server.vhost_https_port,
        "subdomain_host": node.server.subdomain_host,
        "log": _log_context(node.server.log, instance_dir),
        "auth": _auth_context(node.server.auth, instance_dir),
    }
    return template.render(**context)


def _render_client_proxies(instance_dir: Path, proxy_file: ProxyFile, proxies_root: Path) -> list[Path]:
    rendered: list[Path] = []
    for proxy in proxy_file.proxies:
        if not proxy.enabled:
            continue
        template_name = f"proxies/{proxy.type.value}.toml.j2"
        template = ENVIRONMENT.get_template(template_name)
        target = proxies_root / f"{_slugify(proxy.name)}.toml"
        target.write_text(template.render(proxy=_proxy_context(proxy, instance_dir)), encoding="utf-8")
        rendered.append(target)
    return rendered


def _proxy_context(proxy: ProxyConfig, instance_dir: Path) -> dict[str, object]:
    common: dict[str, object] = {
        "name": proxy.name,
        "type": proxy.type.value,
        "description": proxy.description,
        "local_ip": proxy.local_ip,
        "local_port": proxy.local_port,
        "annotations": proxy.annotations,
        "metadatas": proxy.metadatas,
        "transport": {
            "use_encryption": proxy.transport.use_encryption,
            "use_compression": proxy.transport.use_compression,
            "bandwidth_limit": proxy.transport.bandwidth_limit,
            "bandwidth_limit_mode": proxy.transport.bandwidth_limit_mode.value if proxy.transport.bandwidth_limit_mode else None,
        },
        "instance_dir": str(instance_dir),
    }
    if isinstance(proxy, (TcpProxyConfig, UdpProxyConfig)):
        common["remote_port"] = proxy.remote_port
    if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)):
        common["custom_domains"] = proxy.custom_domains
        common["subdomain"] = proxy.subdomain
    return common


def _render_systemd(instance_dir: Path, node: NodeBase, template_name: str) -> str:
    template = ENVIRONMENT.get_template(f"systemd/{template_name}")
    paths = node.resolved_paths(instance_dir)
    low_port = False
    if node.role == Role.SERVER:
        assert isinstance(node, ServerNodeConfig)
        for value in [node.server.bind_port, node.server.vhost_http_port, node.server.vhost_https_port]:
            if value is not None and value < 1024:
                low_port = True
                break
    return template.render(
        service=node.service,
        binary_path=str(paths.binary_path(node.role)),
        config_path=str(paths.config_path(node.role)),
        low_port_capability=low_port,
    )


def _auth_context(auth: AuthConfig, instance_dir: Path) -> dict[str, str | None]:
    return {
        "method": auth.method,
        "token": auth.token,
        "token_file": str(resolve_path_from_instance(auth.token_file, instance_dir)) if auth.token_file else None,
    }


def _log_context(log: FrpLogConfig, instance_dir: Path) -> dict[str, str | int | bool | None]:
    return {
        "to": str(resolve_path_from_instance(log.to, instance_dir)) if log.to else None,
        "level": log.level,
        "max_days": log.max_days,
        "disable_print_color": log.disable_print_color,
    }


def _slugify(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "proxy"
