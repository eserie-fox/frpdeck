"""Create new instance directories and starter configs."""

from __future__ import annotations

from pathlib import Path

from frpdeck.domain.client_config import AuthConfig, ClientCommonConfig, FrpLogConfig, WebServerConfig
from frpdeck.domain.enums import Role
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig
from frpdeck.domain.server_config import ServerCommonConfig
from frpdeck.domain.state import ClientNodeConfig, ServerNodeConfig
from frpdeck.domain.systemd import ServiceConfig
from frpdeck.storage.dump import dump_yaml_model


PLACEHOLDER_SERVER_ADDR = "PLEASE_FILL_SERVER_ADDR"
PLACEHOLDER_TOKEN = "PLEASE_FILL_TOKEN"
PLACEHOLDER_DOMAIN = "PLEASE_FILL_DOMAIN"


def scaffold_instance(base_dir: Path, role: Role, instance_name: str) -> Path:
    """Create an instance directory with starter files."""
    instance_dir = (base_dir / instance_name).resolve()
    instance_dir.mkdir(parents=True, exist_ok=False)
    for relative in [
        "rendered/proxies.d",
        "rendered/systemd",
        "rendered/bin",
        "backups",
        "state",
        "secrets",
    ]:
        (instance_dir / relative).mkdir(parents=True, exist_ok=True)

    service_suffix = "frpc" if role == Role.CLIENT else "frps"
    service = ServiceConfig(service_name=f"frpdeck-{instance_name}-{service_suffix}")

    if role == Role.CLIENT:
        node = ClientNodeConfig(
            instance_name=instance_name,
            service=service,
            client=ClientCommonConfig(
                user=instance_name,
                server_addr=PLACEHOLDER_SERVER_ADDR,
                server_port=7000,
                web_server=WebServerConfig(addr="127.0.0.1", port=7400),
                log=FrpLogConfig(to=Path("runtime/logs/frpc.log"), level="info", max_days=7, disable_print_color=True),
                auth=AuthConfig(token_file=Path("secrets/token.txt")),
            ),
        )
        dump_yaml_model(node, instance_dir / "node.yaml")
        proxies = ProxyFile(
            proxies=[
                TcpProxyConfig(
                    name="sample_tcp",
                    description="Example TCP proxy",
                    local_port=22,
                    remote_port=6000,
                )
            ]
        )
        dump_yaml_model(proxies, instance_dir / "proxies.yaml")
    else:
        node = ServerNodeConfig(
            instance_name=instance_name,
            service=service,
            server=ServerCommonConfig(
                bind_addr="0.0.0.0",
                bind_port=7000,
                subdomain_host=PLACEHOLDER_DOMAIN,
                log=FrpLogConfig(to=Path("runtime/logs/frps.log"), level="info", max_days=7, disable_print_color=True),
                auth=AuthConfig(token_file=Path("secrets/token.txt")),
            ),
        )
        dump_yaml_model(node, instance_dir / "node.yaml")

    (instance_dir / "secrets" / "token.txt.example").write_text(f"{PLACEHOLDER_TOKEN}\n", encoding="utf-8")
    return instance_dir

