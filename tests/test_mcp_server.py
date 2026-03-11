from pathlib import Path
import json

from mcp.server.fastmcp import FastMCP

from frpdeck.domain.client_config import AuthConfig, ClientCommonConfig
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.server_config import ServerCommonConfig
from frpdeck.domain.state import ClientNodeConfig, ServerNodeConfig
from frpdeck.domain.systemd import ServiceConfig
from frpdeck.domain.proxy_management import ApplyReport
from frpdeck.mcp.resources import instance_status_resource, proxy_runtime_status_resource
from frpdeck.mcp.server import create_mcp_server
from frpdeck.mcp.tools import apply_proxy_changes_tool, get_proxy_tool, list_proxies_tool, preview_proxy_changes_tool
from frpdeck.services.renderer import RenderSummary
from frpdeck.storage.dump import dump_json_data, dump_yaml_model


def _write_client_instance(instance_dir: Path) -> None:
    dump_yaml_model(
        ClientNodeConfig(
            instance_name="client-demo",
            service=ServiceConfig(service_name="client-demo-frpc"),
            client=ClientCommonConfig(server_addr="example.com", server_port=7000, auth=AuthConfig(token="secret")),
        ),
        instance_dir / "node.yaml",
    )
    dump_yaml_model(
        ProxyFile(
            proxies=[
                TcpProxyConfig(name="ssh", local_port=22, remote_port=6000),
                UdpProxyConfig(name="dns", local_port=53, remote_port=6001, enabled=False),
            ]
        ),
        instance_dir / "proxies.yaml",
    )
    (instance_dir / "rendered" / "proxies.d").mkdir(parents=True, exist_ok=True)
    (instance_dir / "rendered" / "frpc.toml").write_text("main", encoding="utf-8")
    (instance_dir / "rendered" / "proxies.d" / "ssh.toml").write_text("proxy", encoding="utf-8")
    (instance_dir / "state").mkdir(parents=True, exist_ok=True)
    (instance_dir / "state" / "current_version.txt").write_text("0.61.0\n", encoding="utf-8")
    dump_json_data(
        {
            "applied_at": "2026-03-11T00:00:00+00:00",
            "service_name": "client-demo-frpc",
            "config_path": str(instance_dir / "runtime" / "config" / "frpc.toml"),
        },
        instance_dir / "state" / "last_apply.json",
    )


def _write_server_instance(instance_dir: Path) -> None:
    dump_yaml_model(
        ServerNodeConfig(
            instance_name="server-demo",
            service=ServiceConfig(service_name="server-demo-frps"),
            server=ServerCommonConfig(auth=AuthConfig(token="secret")),
        ),
        instance_dir / "node.yaml",
    )
    dump_yaml_model(ProxyFile(proxies=[]), instance_dir / "proxies.yaml")


def test_mcp_list_proxies_tool_returns_facade_shape(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = list_proxies_tool(str(tmp_path))

    assert result.schema_version == "frpdeck.proxy.v1"
    assert result.ok is True
    assert result.data["count"] == 2


def test_mcp_get_proxy_tool_maps_missing_proxy_to_stable_error(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = get_proxy_tool(str(tmp_path), "missing")

    assert result.ok is False
    assert result.error_code == "proxy_not_found"


def test_mcp_preview_tool_returns_jsonable_data(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = preview_proxy_changes_tool(str(tmp_path))

    assert result.ok is True
    assert result.data["enabled_proxies"] == ["ssh"]
    json.dumps(result.model_dump(mode="json"))


def test_mcp_apply_tool_rejects_server_role(tmp_path: Path) -> None:
    _write_server_instance(tmp_path)

    result = apply_proxy_changes_tool(str(tmp_path))

    assert result.ok is False
    assert result.error_code == "unsupported_role"


def test_mcp_apply_tool_succeeds_with_mocked_render_and_reload(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    def fake_render(instance_dir: Path, node: object, proxy_file: object, output_root: Path | None = None) -> RenderSummary:
        root = output_root or (instance_dir / "rendered")
        rendered_path = root / "proxies.d" / "ssh.toml"
        rendered_path.parent.mkdir(parents=True, exist_ok=True)
        rendered_path.write_text("proxy", encoding="utf-8")
        main_path = root / "frpc.toml"
        main_path.write_text("main", encoding="utf-8")
        systemd_path = root / "systemd" / "client-demo-frpc.service"
        systemd_path.parent.mkdir(parents=True, exist_ok=True)
        systemd_path.write_text("unit", encoding="utf-8")
        return RenderSummary(main_config_path=main_path, rendered_proxy_paths=[rendered_path], systemd_unit_path=systemd_path)

    def fake_sync(instance_dir: Path, node: object) -> Path:
        runtime_path = instance_dir / "runtime" / "config" / "frpc.toml"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text("runtime", encoding="utf-8")
        return runtime_path

    def fake_reload(self: object, instance_dir: Path, node: object) -> str:
        return "reload completed"

    monkeypatch.setattr("frpdeck.services.proxy_manager.render_instance", fake_render)
    monkeypatch.setattr("frpdeck.services.proxy_manager.sync_rendered_to_runtime", fake_sync)
    monkeypatch.setattr("frpdeck.services.proxy_manager.ProxyManager._reload_client", fake_reload)

    result = apply_proxy_changes_tool(str(tmp_path))

    assert result.ok is True
    assert result.data["reloaded"] is True
    assert result.data["rendered_files"] == ["ssh.toml"]


def test_instance_status_resource_returns_json(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    payload = json.loads(instance_status_resource(str(tmp_path)))

    assert payload["schema_version"] == "frpdeck.status.v1"
    assert payload["proxy_counts"]["total"] == 2


def test_proxy_runtime_status_resource_returns_per_proxy_status(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    payload = json.loads(proxy_runtime_status_resource(str(tmp_path)))

    by_name = {item["name"]: item for item in payload}
    assert by_name["ssh"]["included_in_current_render"] is True
    assert by_name["dns"]["included_in_current_render"] is False


def test_create_mcp_server_returns_fastmcp_instance() -> None:
    server = create_mcp_server()

    assert isinstance(server, FastMCP)