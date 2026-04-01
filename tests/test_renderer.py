from pathlib import Path

from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.services.renderer import render_instance
from tests.support import build_client_node, build_server_node


def test_client_render_outputs_main_and_proxy_files(tmp_path: Path) -> None:
    node = build_client_node()
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


def test_client_render_places_includes_before_first_table(tmp_path: Path) -> None:
    node = build_client_node(
        overrides={
            "client": {
                "includes_enabled": True,
            }
        }
    )

    summary = render_instance(tmp_path, node, ProxyFile(proxies=[TcpProxyConfig(name="ssh", local_port=22, remote_port=6000)]))
    main_config = summary.main_config_path.read_text(encoding="utf-8")

    assert 'includes = [' in main_config
    assert main_config.index('includes = [') < main_config.index('[transport]')


def test_server_render_outputs_frps_toml(tmp_path: Path) -> None:
    node = build_server_node()

    summary = render_instance(tmp_path, node)

    assert summary.main_config_path.name == "frps.toml"
    assert summary.main_config_path.exists()


def test_server_render_includes_kcp_bind_port_when_configured(tmp_path: Path) -> None:
    node = build_server_node(
        overrides={
            "server": {
                "bind_port": 48265,
                "kcp_bind_port": 48265,
            }
        }
    )

    summary = render_instance(tmp_path, node)
    main_config = summary.main_config_path.read_text(encoding="utf-8")

    assert "bindPort = 48265" in main_config
    assert "kcpBindPort = 48265" in main_config


def test_server_render_adds_low_port_capability_for_low_kcp_bind_port(tmp_path: Path) -> None:
    node = build_server_node(
        overrides={
            "server": {
                "bind_port": 7000,
                "kcp_bind_port": 443,
                "vhost_http_port": 8080,
                "vhost_https_port": 8443,
            }
        }
    )

    summary = render_instance(tmp_path, node)
    unit_content = summary.systemd_unit_path.read_text(encoding="utf-8")

    assert "AmbientCapabilities=CAP_NET_BIND_SERVICE" in unit_content
