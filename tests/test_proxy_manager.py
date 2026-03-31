from pathlib import Path
import json

import pytest

from frpdeck.domain.errors import ProxyAlreadyExistsError, ProxyConflictError, UnsupportedOperationError
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.proxy_management import ProxyUpdatePatch
from frpdeck.services.proxy_manager import ProxyManager
from frpdeck.services.renderer import RenderSummary
from frpdeck.storage.dump import dump_yaml_model
from frpdeck.storage.load import load_proxy_file
from tests.support import build_client_node, build_server_node


def _load_audit_records(instance_dir: Path) -> list[dict[str, object]]:
    audit_path = instance_dir / "state" / "audit" / "audit.jsonl"
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _revision_dirs(instance_dir: Path) -> list[Path]:
    root = instance_dir / "state" / "revisions"
    return sorted(root.iterdir()) if root.exists() else []


def _write_client_instance(
    instance_dir: Path,
    proxies: list[object] | None = None,
    *,
    instance_name: str = "client-demo",
) -> None:
    node = build_client_node(instance_name=instance_name)
    dump_yaml_model(node, instance_dir / "node.yaml")
    dump_yaml_model(ProxyFile(proxies=list(proxies or [])), instance_dir / "proxies.yaml")


def _write_server_instance(instance_dir: Path) -> None:
    node = build_server_node()
    dump_yaml_model(node, instance_dir / "node.yaml")
    dump_yaml_model(ProxyFile(proxies=[]), instance_dir / "proxies.yaml")


def test_add_proxy_succeeds_and_rejects_duplicates(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    manager = ProxyManager()

    result = manager.add_proxy(
        tmp_path,
        TcpProxyConfig(name="ssh", local_port=22, remote_port=6000),
    )

    assert result.changed is True
    assert result.proxy is not None
    assert result.proxy.name == "ssh"
    assert load_proxy_file(tmp_path).proxies[0].name == "ssh"
    records = _load_audit_records(tmp_path)
    assert len(records) == 1
    assert records[0]["operation"] == "proxy_add"
    assert records[0]["actor"]["source"] == "cli"
    assert records[0]["target"]["proxy_name"] == "ssh"
    revisions = _revision_dirs(tmp_path)
    assert len(revisions) == 1
    assert (revisions[0] / "proxies.before.yaml").exists()
    assert (revisions[0] / "proxies.after.yaml").exists()
    assert (revisions[0] / "meta.json").exists()

    with pytest.raises(ProxyAlreadyExistsError):
        manager.add_proxy(tmp_path, TcpProxyConfig(name="ssh", local_port=23, remote_port=6001))


def test_update_proxy_applies_patch_and_revalidates_model(tmp_path: Path) -> None:
    _write_client_instance(tmp_path, proxies=[TcpProxyConfig(name="ssh", local_port=22, remote_port=6000)])
    manager = ProxyManager()

    result = manager.update_proxy(tmp_path, "ssh", ProxyUpdatePatch(local_port=2222, remote_port=7000))

    assert result.proxy is not None
    assert result.proxy.local_port == 2222
    assert result.proxy.remote_port == 7000
    record = _load_audit_records(tmp_path)[0]
    assert record["operation"] == "proxy_update"
    assert record["before"]["proxy"]["local_port"] == 22
    assert record["after"]["proxy"]["local_port"] == 2222

    with pytest.raises(ProxyConflictError):
        manager.update_proxy(tmp_path, "ssh", {"remote_port": 70000})


def test_enable_and_disable_proxy_flip_enabled_state(tmp_path: Path) -> None:
    _write_client_instance(tmp_path, proxies=[TcpProxyConfig(name="ssh", local_port=22, remote_port=6000)])
    manager = ProxyManager()

    manager.disable_proxy(tmp_path, "ssh")
    assert load_proxy_file(tmp_path).proxies[0].enabled is False

    manager.enable_proxy(tmp_path, "ssh")
    assert load_proxy_file(tmp_path).proxies[0].enabled is True
    records = _load_audit_records(tmp_path)
    assert [record["operation"] for record in records] == ["proxy_disable", "proxy_enable"]
    assert records[0]["after"]["proxy"]["enabled"] is False
    assert records[1]["after"]["proxy"]["enabled"] is True


def test_remove_proxy_soft_disables_and_hard_deletes(tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path,
        proxies=[
            TcpProxyConfig(name="ssh", local_port=22, remote_port=6000),
            UdpProxyConfig(name="dns", local_port=53, remote_port=6001),
        ],
    )
    manager = ProxyManager()

    soft_result = manager.remove_proxy(tmp_path, "ssh")
    assert soft_result.changed is True
    assert load_proxy_file(tmp_path).proxies[0].enabled is False

    hard_result = manager.remove_proxy(tmp_path, "dns", soft=False)
    assert hard_result.removed_name == "dns"
    assert [proxy.name for proxy in load_proxy_file(tmp_path).proxies] == ["ssh"]
    records = _load_audit_records(tmp_path)
    assert records[0]["operation"] == "proxy_remove"
    assert records[0]["target"]["remove_mode"] == "soft"
    assert records[1]["operation"] == "proxy_remove"
    assert records[1]["target"]["remove_mode"] == "hard"


def test_validate_proxy_set_reports_remote_port_conflicts(tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path,
        proxies=[
            TcpProxyConfig(name="ssh-a", local_port=22, remote_port=6000),
            TcpProxyConfig(name="ssh-b", local_port=2222, remote_port=6000),
        ],
    )
    manager = ProxyManager()

    report = manager.validate_proxy_set(tmp_path)

    assert report.ok is False
    assert any("duplicate tcp remote_port: 6000" in error for error in report.errors)


def test_preview_proxy_changes_returns_summary_without_touching_rendered_dir(tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path,
        proxies=[
            TcpProxyConfig(name="ssh", local_port=22, remote_port=6000),
            UdpProxyConfig(name="dns", local_port=53, remote_port=6001, enabled=False),
        ],
    )
    rendered_file = tmp_path / "rendered" / "proxies.d" / "existing.toml"
    rendered_file.parent.mkdir(parents=True, exist_ok=True)
    rendered_file.write_text("sentinel", encoding="utf-8")

    report = ProxyManager().preview_proxy_changes(tmp_path)

    assert report.ok is True
    assert report.enabled_proxies == ["ssh"]
    assert report.disabled_proxies == ["dns"]
    assert report.rendered_proxy_files == ["ssh.toml"]
    assert rendered_file.read_text(encoding="utf-8") == "sentinel"


def test_apply_proxy_changes_runs_render_sync_and_reload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path, proxies=[TcpProxyConfig(name="ssh", local_port=22, remote_port=6000)])
    manager = ProxyManager()
    calls: list[str] = []

    def fake_render(instance_dir: Path, node: object, proxy_file: object, output_root: Path | None = None) -> RenderSummary:
        calls.append("render")
        rendered_path = (output_root or (instance_dir / "rendered")) / "proxies.d" / "ssh.toml"
        rendered_path.parent.mkdir(parents=True, exist_ok=True)
        rendered_path.write_text("proxy", encoding="utf-8")
        main_path = (output_root or (instance_dir / "rendered")) / "frpc.toml"
        main_path.write_text("main", encoding="utf-8")
        systemd_path = (output_root or (instance_dir / "rendered")) / "systemd" / "client-demo-frpc.service"
        systemd_path.parent.mkdir(parents=True, exist_ok=True)
        systemd_path.write_text("unit", encoding="utf-8")
        return RenderSummary(main_config_path=main_path, rendered_proxy_paths=[rendered_path], systemd_unit_path=systemd_path)

    def fake_sync(instance_dir: Path, node: object) -> Path:
        calls.append("sync")
        runtime_path = instance_dir / "runtime" / "config" / "frpc.toml"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text("runtime", encoding="utf-8")
        return runtime_path

    def fake_reload(self: ProxyManager, instance_dir: Path, node: object) -> str:
        calls.append("reload")
        return "reload completed"

    monkeypatch.setattr("frpdeck.services.proxy_manager.render_instance", fake_render)
    monkeypatch.setattr("frpdeck.services.proxy_manager.sync_rendered_to_runtime", fake_sync)
    monkeypatch.setattr(ProxyManager, "_reload_client", fake_reload)

    report = manager.apply_proxy_changes(tmp_path)

    assert report.ok is True
    assert report.rendered_proxy_files == ["ssh.toml"]
    assert report.reloaded is True
    assert calls == ["render", "sync", "reload"]
    records = _load_audit_records(tmp_path)
    assert records[0]["operation"] == "proxy_apply"
    assert records[0]["result"]["ok"] is True
    assert records[0]["result"]["reload_requested"] is True
    assert records[0]["result"]["reloaded"] is True
    assert _revision_dirs(tmp_path) == []


def test_apply_proxy_changes_rejects_server_instance(tmp_path: Path) -> None:
    _write_server_instance(tmp_path)

    with pytest.raises(UnsupportedOperationError):
        ProxyManager().apply_proxy_changes(tmp_path)


def test_proxy_write_surfaces_audit_failure_as_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    monkeypatch.setattr("frpdeck.services.proxy_manager.record_audit_event", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))

    result = ProxyManager().add_proxy(tmp_path, TcpProxyConfig(name="ssh", local_port=22, remote_port=6000))

    assert result.changed is True
    assert result.warnings
    assert "audit log append failed" in result.warnings[0]


def test_audit_records_keep_logical_instance_name_when_directory_differs(tmp_path: Path) -> None:
    instance_dir = tmp_path / "physical-dir"
    _write_client_instance(instance_dir, instance_name="logical-instance")

    ProxyManager().add_proxy(instance_dir, TcpProxyConfig(name="ssh", local_port=22, remote_port=6000))

    record = _load_audit_records(instance_dir)[0]
    assert record["instance_dir"] == str(instance_dir.resolve())
    assert record["instance_name"] == "logical-instance"
