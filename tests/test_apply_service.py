from pathlib import Path

from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig
from frpdeck.services.apply_service import ApplyExecutionResult, ApplyService
from frpdeck.services.renderer import RenderSummary
from frpdeck.storage.dump import dump_yaml_model
from tests.support import build_client_node


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def step_started(self, index: int, total: int, message: str) -> None:
        self.events.append(("step_started", index, total, message))

    def step_succeeded(self, message: str) -> None:
        self.events.append(("step_succeeded", message))

    def step_skipped(self, message: str) -> None:
        self.events.append(("step_skipped", message))

    def download_started(self, asset_name: str) -> None:
        self.events.append(("download_started", asset_name))

    def download_progress(self, downloaded_bytes: int, total_bytes: int | None) -> None:
        self.events.append(("download_progress", downloaded_bytes, total_bytes))

    def download_finished(self, asset_name: str) -> None:
        self.events.append(("download_finished", asset_name))


def _write_client_instance(instance_dir: Path) -> None:
    dump_yaml_model(build_client_node(), instance_dir / "node.yaml")
    dump_yaml_model(ProxyFile(proxies=[TcpProxyConfig(name="ssh", local_port=22, remote_port=6000)]), instance_dir / "proxies.yaml")


def test_apply_service_runs_successful_workflow_in_order(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    reporter = _Recorder()
    calls: list[str] = []

    monkeypatch.setattr(
        "frpdeck.services.apply_service.validate_instance",
        lambda instance_dir, node, proxies: calls.append("validate") or [],
    )

    def fake_render(instance_dir: Path, node, proxies) -> RenderSummary:
        calls.append("render")
        systemd_unit_path = instance_dir / "rendered" / "systemd" / "client-demo-frpc.service"
        systemd_unit_path.parent.mkdir(parents=True, exist_ok=True)
        systemd_unit_path.write_text("unit", encoding="utf-8")
        return RenderSummary(
            main_config_path=instance_dir / "rendered" / "frpc.toml",
            rendered_proxy_paths=[instance_dir / "rendered" / "proxies.d" / "ssh.toml"],
            systemd_unit_path=systemd_unit_path,
        )

    monkeypatch.setattr("frpdeck.services.apply_service.render_instance", fake_render)
    monkeypatch.setattr("frpdeck.services.apply_service.read_current_version", lambda instance_dir: None)

    def fake_ensure_binary_installed(
        instance_dir: Path,
        node,
        *,
        archive: Path | None = None,
        progress=None,
        download_started=None,
        download_finished=None,
    ) -> str:
        calls.append("install_binary")
        if download_started is not None:
            download_started("frp.tar.gz")
        if progress is not None:
            progress(5, 10)
        if download_finished is not None:
            download_finished("frp.tar.gz")
        return "0.65.0"

    monkeypatch.setattr("frpdeck.services.apply_service.ensure_binary_installed", fake_ensure_binary_installed)
    monkeypatch.setattr(
        "frpdeck.services.apply_service.sync_rendered_to_runtime",
        lambda instance_dir, node: calls.append("sync_runtime") or (instance_dir / "runtime" / "config" / "frpc.toml"),
    )
    monkeypatch.setattr(
        "frpdeck.services.apply_service.install_unit",
        lambda rendered_unit, target_unit: calls.append("install_unit"),
    )
    monkeypatch.setattr("frpdeck.services.apply_service.daemon_reload", lambda: calls.append("daemon_reload"))
    monkeypatch.setattr("frpdeck.services.apply_service.enable_service", lambda service_name: calls.append("enable_service"))
    monkeypatch.setattr("frpdeck.services.apply_service.restart_service", lambda service_name: calls.append("restart_service"))

    result = ApplyService().apply_instance(tmp_path, reporter=reporter)

    assert result == ApplyExecutionResult(
        ok=True,
        service_name="client-demo-frpc",
        validation_errors=[],
        config_path=tmp_path / "runtime" / "config" / "frpc.toml",
        binary_version="0.65.0",
    )
    assert calls == [
        "validate",
        "render",
        "install_binary",
        "sync_runtime",
        "install_unit",
        "daemon_reload",
        "enable_service",
        "restart_service",
    ]
    assert ("download_started", "frp.tar.gz") in reporter.events
    assert ("download_progress", 5, 10) in reporter.events
    assert ("download_finished", "frp.tar.gz") in reporter.events
    assert (tmp_path / "state" / "last_apply.json").exists()


def test_apply_service_stops_after_validation_failure(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    monkeypatch.setattr(
        "frpdeck.services.apply_service.validate_instance",
        lambda instance_dir, node, proxies: ["client.server_addr still uses a placeholder value"],
    )
    monkeypatch.setattr(
        "frpdeck.services.apply_service.render_instance",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render should not run")),
    )
    monkeypatch.setattr(
        "frpdeck.services.apply_service.ensure_binary_installed",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("install should not run")),
    )

    result = ApplyService().apply_instance(tmp_path)

    assert result.ok is False
    assert result.service_name == "client-demo-frpc"
    assert result.validation_errors == ["client.server_addr still uses a placeholder value"]
    assert not (tmp_path / "state" / "last_apply.json").exists()
