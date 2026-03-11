from pathlib import Path

from frpdeck.domain.client_config import AuthConfig, ClientCommonConfig
from frpdeck.domain.errors import CommandExecutionError
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.state import ApplyState, ClientNodeConfig
from frpdeck.domain.systemd import ServiceConfig
from frpdeck.services.status_service import StatusService
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
        ApplyState.create(service_name="client-demo-frpc", config_path=instance_dir / "runtime" / "config" / "frpc.toml").model_dump(mode="json"),
        instance_dir / "state" / "last_apply.json",
    )


def test_get_instance_status_returns_aggregated_fields(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    monkeypatch.setattr("frpdeck.services.status_service.status_service", lambda service_name: "Active: active (running)")

    status = StatusService().get_instance_status(tmp_path)

    assert status.schema_version == "frpdeck.status.v1"
    assert status.proxy_counts.total == 2
    assert status.proxy_counts.enabled == 1
    assert status.current_version == "0.61.0"
    assert status.render_summary.main_config_exists is True
    assert status.render_summary.rendered_proxy_files == ["ssh.toml"]
    assert status.last_apply is not None
    assert status.last_apply.service_name == "client-demo-frpc"


def test_get_proxy_runtime_status_reports_disabled_and_rendered_state(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    statuses = StatusService().get_proxy_runtime_status(tmp_path)

    by_name = {status.name: status for status in statuses}
    assert by_name["ssh"].included_in_current_render is True
    assert by_name["dns"].included_in_current_render is False
    assert "disabled so not rendered" in by_name["dns"].notes


def test_get_instance_status_gracefully_degrades_when_systemctl_unavailable(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    def fail_status(service_name: str) -> str:
        raise CommandExecutionError("systemctl missing")

    monkeypatch.setattr("frpdeck.services.status_service.status_service", fail_status)

    status = StatusService().get_instance_status(tmp_path)

    assert status.errors == []
    assert status.service_status.available is False
    assert any("service status unavailable" in warning for warning in status.warnings)