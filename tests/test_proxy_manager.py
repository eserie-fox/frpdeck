from pathlib import Path
import json

import pytest

from frpdeck.domain.errors import ProxyAlreadyExistsError, ProxyConflictError
from frpdeck.domain.proxy import HttpProxyConfig, HttpsProxyConfig, ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.proxy_management import ProxyUpdatePatch
from frpdeck.services.proxy_manager import ProxyManager
from frpdeck.storage.dump import dump_yaml_model
from frpdeck.storage.load import load_proxy_file
from tests.support import build_client_node


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


def test_import_proxy_file_adds_one_proxy_mapping(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    import_file = tmp_path / "web.yaml"
    import_file.write_text(
        "\n".join(
            [
                "name: imported-web",
                "type: https",
                "local_port: 8443",
                "custom_domains:",
                "  - secure.example.com",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = ProxyManager().import_proxy_file(tmp_path, import_file)

    assert result.changed is True
    assert result.proxy is not None
    assert result.proxy.name == "imported-web"
    assert load_proxy_file(tmp_path).proxies[-1].name == "imported-web"


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


def test_validate_proxy_set_accepts_http_and_https_route_variants(tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path,
        proxies=[
            HttpProxyConfig(name="web-domains", local_port=8080, custom_domains=["example.com"]),
            HttpsProxyConfig(name="secure-domains", local_port=8443, custom_domains=["secure.example.com"]),
            HttpProxyConfig(name="web-subdomain", local_port=8081, subdomain="app"),
            HttpProxyConfig(name="web-both", local_port=8082, custom_domains=["both.example.com"], subdomain="combo"),
        ],
    )

    report = ProxyManager().validate_proxy_set(tmp_path)

    assert report.ok is True
    assert report.errors == []


def test_add_and_update_proxy_reject_invalid_http_routes(tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path, proxies=[HttpProxyConfig(name="web", local_port=8080, custom_domains=["example.com"])]
    )
    manager = ProxyManager()
    before_add = (tmp_path / "proxies.yaml").read_text(encoding="utf-8")

    with pytest.raises(ProxyConflictError, match="requires custom_domains or subdomain"):
        manager.add_proxy(tmp_path, {"name": "invalid-web", "type": "http", "local_port": 8081})

    assert (tmp_path / "proxies.yaml").read_text(encoding="utf-8") == before_add

    with pytest.raises(ProxyConflictError, match="requires custom_domains or subdomain"):
        manager.update_proxy(tmp_path, "web", ProxyUpdatePatch(custom_domains=[], subdomain=None))

    assert load_proxy_file(tmp_path).proxies[0].name == "web"


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


def test_proxy_write_surfaces_audit_failure_as_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    monkeypatch.setattr(
        "frpdeck.services.proxy_manager.record_audit_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

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
