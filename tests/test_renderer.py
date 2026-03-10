from pathlib import Path

from frpdeck.domain.client_config import AuthConfig, ClientCommonConfig
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.server_config import ServerCommonConfig
from frpdeck.domain.state import ClientNodeConfig, ServerNodeConfig
from frpdeck.domain.systemd import ServiceConfig
from frpdeck.services.renderer import render_instance


def test_client_render_outputs_main_and_proxy_files(tmp_path: Path) -> None:
    node = ClientNodeConfig(
        instance_name="client-demo",
        service=ServiceConfig(service_name="client-demo-frpc"),
        client=ClientCommonConfig(
            server_addr="example.com",
            server_port=7000,
            auth=AuthConfig(token="secret"),
        ),
    )
    proxies = ProxyFile(
        proxies=[
            TcpProxyConfig(name="ssh", local_port=22, remote_port=6000),
            UdpProxyConfig(name="dns", local_port=53, remote_port=6001, enabled=False),
        ]
    )

    summary = render_instance(tmp_path, node, proxies)

    assert summary.main_config_path.exists()
    assert (tmp_path / "rendered" / "proxies.d" / "ssh.toml").exists()
    assert not (tmp_path / "rendered" / "proxies.d" / "dns.toml").exists()


def test_server_render_outputs_frps_toml(tmp_path: Path) -> None:
    node = ServerNodeConfig(
        instance_name="server-demo",
        service=ServiceConfig(service_name="server-demo-frps"),
        server=ServerCommonConfig(auth=AuthConfig(token="secret")),
    )

    summary = render_instance(tmp_path, node)

    assert summary.main_config_path.name == "frps.toml"
    assert summary.main_config_path.exists()
