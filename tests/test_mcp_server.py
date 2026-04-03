from pathlib import Path
import json
import logging

import anyio
from mcp.server.fastmcp import FastMCP
import pytest

from frpdeck.domain.errors import ConfigLoadError
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.mcp.resources import instance_status_resource, proxy_runtime_status_resource
from frpdeck.mcp.server import create_mcp_server, main
from frpdeck.mcp.tools import add_proxy_tool, get_proxy_tool, import_proxy_file_tool, list_proxies_tool, preview_proxy_changes_tool
from frpdeck.storage.dump import dump_json_data, dump_yaml_model
from tests.support import build_client_node


def _write_client_instance(instance_dir: Path, *, node_overrides: dict[str, object] | None = None) -> None:
    dump_yaml_model(
        build_client_node(overrides=node_overrides),
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
def _list_tools(server: FastMCP) -> dict[str, object]:
    async def run() -> dict[str, object]:
        return {tool.name: tool for tool in await server.list_tools()}

    return anyio.run(run)


def _list_resources(server: FastMCP) -> list[object]:
    async def run() -> list[object]:
        return await server.list_resources()

    return anyio.run(run)


def _call_tool(server: FastMCP, name: str, arguments: dict[str, object]) -> dict[str, object]:
    async def run() -> dict[str, object]:
        _, structured = await server.call_tool(name, arguments)
        assert isinstance(structured, dict)
        return structured

    return anyio.run(run)


def _read_resource(server: FastMCP, uri: str) -> list[object]:
    async def run() -> list[object]:
        return await server.read_resource(uri)

    return anyio.run(run)


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


def test_mcp_add_proxy_tool_supports_all_protocols(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    tcp_result = add_proxy_tool(str(tmp_path), protocol="tcp", name="ssh-alt", local_port=2222, remote_port=7000)
    udp_result = add_proxy_tool(str(tmp_path), protocol="udp", name="dns-alt", local_port=5353, remote_port=7001)
    http_result = add_proxy_tool(
        str(tmp_path),
        protocol="http",
        name="web",
        local_port=8080,
        custom_domains=["app.example.com"],
    )
    https_result = add_proxy_tool(
        str(tmp_path),
        protocol="https",
        name="secure-web",
        local_port=8443,
        subdomain="secure",
    )

    assert tcp_result.ok is True
    assert tcp_result.data["proxy"]["type"] == "tcp"
    assert udp_result.ok is True
    assert udp_result.data["proxy"]["type"] == "udp"
    assert http_result.ok is True
    assert http_result.data["proxy"]["custom_domains"] == ["app.example.com"]
    assert https_result.ok is True
    assert https_result.data["proxy"]["subdomain"] == "secure"


def test_mcp_import_proxy_file_tool_imports_mapping(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    import_file = tmp_path / "web.yaml"
    import_file.write_text(
        "\n".join(
            [
                "name: imported-web",
                "type: http",
                "local_port: 8080",
                "custom_domains:",
                "  - imported.example.com",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = import_proxy_file_tool(str(tmp_path), str(import_file))

    assert result.ok is True
    assert result.operation == "import_proxy_file"
    assert result.data["proxy"]["name"] == "imported-web"


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


def test_server_info_tool_is_callable_and_jsonable(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    payload = _call_tool(create_mcp_server(tmp_path), "server_info", {})

    assert payload["ok"] is True
    assert payload["mode"] == "bound"
    assert payload["bound_instance"] == str(tmp_path.resolve())
    assert payload["server_name"] == "frpdeck"
    json.dumps(payload)


def test_generic_mode_tool_schema_keeps_instance_dir() -> None:
    tools = _list_tools(create_mcp_server())

    assert "instance_dir" in tools["list_proxies"].inputSchema["properties"]
    assert "instance_dir" in tools["add_proxy"].inputSchema["properties"]
    assert "instance_dir" in tools["import_proxy_file"].inputSchema["properties"]
    assert tools["add_proxy"].inputSchema["properties"]["protocol"]["enum"] == ["tcp", "udp", "http", "https"]
    assert "apply_proxy_changes" not in tools
    assert "validate_proxy_set" not in tools


def test_bound_mode_tool_schema_omits_instance_dir() -> None:
    tools = _list_tools(create_mcp_server(Path(".")))

    assert "instance_dir" not in tools["list_proxies"].inputSchema.get("properties", {})
    assert "instance_dir" not in tools["add_proxy"].inputSchema.get("properties", {})
    assert "instance_dir" not in tools["import_proxy_file"].inputSchema.get("properties", {})


def test_bound_and_generic_modes_expose_same_tool_names_with_expected_instance_dir_difference() -> None:
    generic_tools = _list_tools(create_mcp_server())
    bound_tools = _list_tools(create_mcp_server(Path(".")))

    assert set(generic_tools) == set(bound_tools)
    for name in generic_tools:
        generic_properties = generic_tools[name].inputSchema.get("properties", {})
        bound_properties = bound_tools[name].inputSchema.get("properties", {})
        if name == "server_info":
            assert "instance_dir" not in generic_properties
            assert "instance_dir" not in bound_properties
            continue
        assert "instance_dir" in generic_properties
        assert "instance_dir" not in bound_properties


def test_bound_mode_resources_are_parameterless_and_readable(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    server = create_mcp_server(tmp_path)

    resources = _list_resources(server)
    uris = {str(resource.uri) for resource in resources}
    contents = _read_resource(server, "frpdeck://instance/status")

    assert "frpdeck://instance/status" in uris
    assert "frpdeck://instance/proxy-runtime-status" in uris
    payload = json.loads(contents[0].content)
    assert payload["schema_version"] == "frpdeck.status.v1"
    assert payload["instance"] == str(tmp_path.resolve())


def test_mcp_tool_unknown_exception_returns_stable_error(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    def boom(instance_dir: str, *, facade: object | None = None) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr("frpdeck.mcp.tools.list_proxies_tool", boom)

    payload = _call_tool(create_mcp_server(), "list_proxies", {"instance_dir": str(tmp_path)})

    assert payload["ok"] is False
    assert payload["error_code"] == "internal_error"
    assert payload["errors"] == ["boom"]
    json.dumps(payload)


def test_mcp_main_accepts_instance_dir_without_stdout(monkeypatch, tmp_path: Path, capsys) -> None:
    _write_client_instance(tmp_path)
    calls: list[FastMCP] = []

    def fake_run(self: FastMCP) -> None:
        calls.append(self)

    monkeypatch.setattr("frpdeck.mcp.server.FastMCP.run", fake_run)

    main(["--instance-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert calls


def test_mcp_main_uses_instance_logging_without_stdout(monkeypatch, tmp_path: Path, capsys) -> None:
    _write_client_instance(
        tmp_path,
        node_overrides={
            "frpdeck_logging": {
                "level": "INFO",
                "stream": "none",
                "file_path": "state/logs/frpdeck.log",
            }
        },
    )
    calls: list[FastMCP] = []

    def fake_run(self: FastMCP) -> None:
        logging.getLogger("frpdeck.mcp").info("bound instance logging active")
        calls.append(self)

    monkeypatch.setattr("frpdeck.mcp.server.FastMCP.run", fake_run)

    main(["--instance-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert calls
    assert (tmp_path / "state" / "logs" / "frpdeck.log").is_symlink()


def test_mcp_main_bound_mode_fails_fast_on_invalid_instance_logging(monkeypatch, tmp_path: Path) -> None:
    calls: list[FastMCP] = []

    def fake_run(self: FastMCP) -> None:
        calls.append(self)

    monkeypatch.setattr("frpdeck.mcp.server.FastMCP.run", fake_run)
    (tmp_path / "node.yaml").write_text(
        "\n".join(
            [
                "instance_name: demo-client",
                "role: client",
                "service:",
                "  service_name: demo-frpc",
                "frpdeck_logging:",
                "  level: WARN",
                "client:",
                "  server_addr: example.com",
                "  auth:",
                "    token: secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="invalid node config"):
        main(["--instance-dir", str(tmp_path)])

    assert not calls


def test_mcp_write_audit_marks_actor_as_mcp(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    payload = _call_tool(
        create_mcp_server(tmp_path),
        "add_proxy",
        {"protocol": "tcp", "name": "new-ssh", "local_ip": "127.0.0.1", "local_port": 2200, "remote_port": 6200},
    )

    assert payload["ok"] is True
    audit_path = tmp_path / "state" / "audit" / "audit.jsonl"
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records[-1]["actor"]["source"] == "mcp"
    assert records[-1]["actor"]["mode"] == "bound"
