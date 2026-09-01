import json
import logging
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from typer.main import get_command
from typer.testing import CliRunner

from frpdeck.cli import app
from frpdeck.commands.mcp import WRAPPER_FILENAME
from frpdeck.domain.errors import CommandExecutionError, PermissionOperationError
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.status_models import (
    ConfigSummary,
    InstanceStatus,
    ProxyCounts,
    RenderSummaryStatus,
    ServiceRuntimeStatus,
)
from frpdeck.services.apply_service import ApplyExecutionResult
from frpdeck.storage.dump import dump_yaml_model
from frpdeck.version import __version__
from tests.support import build_client_node, build_server_node

RUNNER = CliRunner()
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "instances"


def _load_audit_records(instance_dir: Path) -> list[dict[str, object]]:
    audit_path = instance_dir / "state" / "audit" / "audit.jsonl"
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


def _write_server_instance(instance_dir: Path) -> None:
    dump_yaml_model(
        build_server_node(),
        instance_dir / "node.yaml",
    )


def _write_rendered_client_snapshot(instance_dir: Path, *, proxy_names: list[str] | None = None) -> None:
    proxy_names = proxy_names or ["ssh"]
    rendered_root = instance_dir / "rendered"
    (rendered_root / "frpc.toml").parent.mkdir(parents=True, exist_ok=True)
    (rendered_root / "frpc.toml").write_text("serverAddr = 'example.com'\n", encoding="utf-8")
    proxies_dir = rendered_root / "proxies.d"
    proxies_dir.mkdir(parents=True, exist_ok=True)
    for proxy_name in proxy_names:
        (proxies_dir / f"{proxy_name}.toml").write_text(f'[[proxies]]\nname = "{proxy_name}"\n', encoding="utf-8")


def _copy_fixture_instance(name: str, destination: Path) -> Path:
    instance_dir = destination / name
    shutil.copytree(FIXTURE_ROOT / name, instance_dir)
    return instance_dir


def _patch_privilege_noop(monkeypatch, module: str) -> None:
    monkeypatch.setattr(f"{module}.maybe_reexec_with_sudo", lambda **kwargs: False)
    monkeypatch.setattr(f"{module}.raise_for_missing_privileges", lambda **kwargs: None)


def _patch_privilege_reexec(monkeypatch, module: str) -> None:
    monkeypatch.setattr(f"{module}.maybe_reexec_with_sudo", lambda **kwargs: True)


def _patch_privilege_fail(monkeypatch, module: str, message: str) -> None:
    monkeypatch.setattr(f"{module}.maybe_reexec_with_sudo", lambda **kwargs: False)
    monkeypatch.setattr(
        f"{module}.raise_for_missing_privileges",
        lambda **kwargs: (_ for _ in ()).throw(PermissionOperationError(message)),
    )


def _registered_command(*path: str) -> Any:
    command = get_command(app)
    for name in path:
        command = _registered_subcommands(command)[name]
    return command


def _registered_subcommands(command: Any) -> dict[str, Any]:
    commands = getattr(command, "commands", None)
    assert isinstance(commands, dict)
    return commands


def _registered_parameter(command: Any, name: str) -> Any:
    matches = [parameter for parameter in command.params if parameter.name == name]
    assert len(matches) == 1
    return matches[0]


def _registered_option(command: Any, name: str) -> Any:
    parameter = _registered_parameter(command, name)
    assert hasattr(parameter, "opts")
    assert hasattr(parameter, "secondary_opts")
    return parameter


def test_init_client_creates_base_files(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["init", "client", "demo-node", "--directory", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "demo-node" / "node.yaml").exists()
    assert (tmp_path / "demo-node" / "proxies.yaml").exists()
    assert (tmp_path / "demo-node" / "secrets" / "token.txt.example").exists()
    assert (tmp_path / "demo-node" / "rendered" / "proxies.d").is_dir()
    assert (tmp_path / "demo-node" / "rendered" / "systemd").is_dir()
    assert (tmp_path / "demo-node" / "rendered" / "bin").is_dir()
    assert (tmp_path / "demo-node" / "backups").is_dir()
    assert (tmp_path / "demo-node" / "state").is_dir()
    assert (tmp_path / "demo-node" / "secrets").is_dir()
    node_payload = yaml.safe_load((tmp_path / "demo-node" / "node.yaml").read_text(encoding="utf-8"))
    proxies_payload = yaml.safe_load((tmp_path / "demo-node" / "proxies.yaml").read_text(encoding="utf-8"))
    assert node_payload["client"]["server_addr"] == "PLEASE_FILL_SERVER_ADDR"
    assert node_payload["client"]["auth"]["token_file"] == "secrets/token.txt"
    assert node_payload["client"]["log"]["to"] == "runtime/logs/frpc.log"
    assert node_payload["client"]["server_port"] == 7000
    assert node_payload["client"]["web_server"]["enable"] is True
    assert node_payload["frpdeck_logging"]["file_path"] == "state/logs/frpdeck.log"
    assert node_payload["frpdeck_logging"]["stream"] == "stderr"
    assert node_payload["service"]["service_name"] == "frpdeck-demo-node-frpc"
    assert proxies_payload["proxies"][0]["name"] == "sample_http"
    assert proxies_payload["proxies"][0]["type"] == "http"
    assert proxies_payload["proxies"][0]["local_port"] == 8080
    assert proxies_payload["proxies"][0]["custom_domains"] == ["PLEASE_FILL_DOMAIN"]
    assert (tmp_path / "demo-node" / "secrets" / "token.txt.example").read_text(
        encoding="utf-8"
    ) == "PLEASE_FILL_TOKEN\n"


def test_init_server_skips_proxy_file(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["init", "server", "demo-node", "--directory", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "demo-node" / "node.yaml").exists()
    assert not (tmp_path / "demo-node" / "proxies.yaml").exists()
    assert (tmp_path / "demo-node" / "secrets" / "token.txt.example").exists()
    node_payload = yaml.safe_load((tmp_path / "demo-node" / "node.yaml").read_text(encoding="utf-8"))
    assert "vhost_http_port" not in node_payload["server"]
    assert "vhost_https_port" not in node_payload["server"]
    assert "subdomain_host" not in node_payload["server"]
    assert node_payload["service"]["service_name"] == "frpdeck-demo-node-frps"


def test_render_succeeds_on_example_instance(tmp_path: Path) -> None:
    instance = _copy_fixture_instance("client-node", tmp_path)

    assert not (instance / "rendered" / "frpc.toml").exists()

    result = RUNNER.invoke(app, ["render", "--instance", str(instance)])

    assert result.exit_code == 0, result.stdout
    assert (instance / "rendered" / "frpc.toml").exists()
    assert (instance / "rendered" / "proxies.d" / "example_web_http.toml").exists()
    assert (instance / "rendered" / "proxies.d" / "example_ssh_tcp.toml").exists()


def test_render_and_validate_server_without_proxy_file(tmp_path: Path) -> None:
    dump_yaml_model(
        build_server_node(overrides={"server": {"subdomain_host": "example.com"}}),
        tmp_path / "node.yaml",
    )

    assert not (tmp_path / "proxies.yaml").exists()

    render_result = RUNNER.invoke(app, ["render", "--instance", str(tmp_path)])

    assert render_result.exit_code == 0, render_result.stdout
    assert (tmp_path / "rendered" / "frps.toml").exists()

    validate_result = RUNNER.invoke(app, ["validate", "--instance", str(tmp_path)])

    assert validate_result.exit_code == 0, validate_result.stdout


def test_validate_rejects_placeholder_config() -> None:
    instance = FIXTURE_ROOT / "client-node"

    result = RUNNER.invoke(app, ["validate", "--instance", str(instance)])

    assert result.exit_code == 1


def test_version_option_returns_success() -> None:
    result = RUNNER.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "1.2.0"
    assert __version__ == "1.2.0"


def test_cli_registers_supported_command_tree_without_relying_on_help_rendering() -> None:
    root = _registered_command()
    root_commands = _registered_subcommands(root)
    assert {
        "init",
        "apply",
        "status",
        "proxy",
        "validate",
        "render",
        "sync",
        "reload",
        "restart",
        "doctor",
        "check-update",
        "upgrade",
        "uninstall",
        "audit",
        "mcp",
    } <= set(root_commands)

    proxy = _registered_command("proxy")
    proxy_commands = _registered_subcommands(proxy)
    assert {"list", "show", "add", "update", "enable", "disable", "import", "preview", "remove"} <= set(proxy_commands)
    assert {"validate", "apply", "add-tcp", "add-http", "add-https"}.isdisjoint(proxy_commands)

    proxy_add = _registered_command("proxy", "add")
    assert {"tcp", "udp", "http", "https"} <= set(_registered_subcommands(proxy_add))

    mcp = _registered_command("mcp")
    assert {"install-stdio-wrapper", "uninstall-stdio-wrapper"} <= set(_registered_subcommands(mcp))

    audit = _registered_command("audit")
    assert "recent" in _registered_subcommands(audit)


def test_cli_exposes_stable_option_contracts_without_parsing_help_output() -> None:
    init = _registered_command("init")
    assert _registered_parameter(init, "role").required is True
    assert _registered_parameter(init, "instance_name").required is True

    apply = _registered_command("apply")
    install_if_missing = _registered_option(apply, "install_if_missing")
    assert install_if_missing.opts == ["--install-if-missing"]
    assert install_if_missing.secondary_opts == ["--no-install-if-missing"]
    assert install_if_missing.default is True

    remove = _registered_command("proxy", "remove")
    remove_parameter_names = {parameter.name for parameter in remove.params}
    remove_flags = {
        flag
        for parameter in remove.params
        for flag in (*getattr(parameter, "opts", ()), *getattr(parameter, "secondary_opts", ()))
    }
    assert {"soft", "remove_mode"}.isdisjoint(remove_parameter_names)
    assert {"--hard", "--soft"}.isdisjoint(remove_flags)

    install_wrapper = _registered_command("mcp", "install-stdio-wrapper")
    ssh_host = _registered_option(install_wrapper, "ssh_host")
    assert ssh_host.opts == ["--ssh-host"]
    assert ssh_host.default is None


def test_apply_fails_fast_with_root_reasons_before_side_effects(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.apply",
        "apply requires elevated privileges for this instance:\n- will manage system service via systemctl\nRetry with: frpdeck apply --instance x --sudo\nOr run manually: sudo frpdeck apply --instance x",
    )
    monkeypatch.setattr("frpdeck.commands.apply.instance_lock", lambda *args, **kwargs: calls.append("lock"))
    monkeypatch.setattr(
        "frpdeck.commands.apply.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr(
        "frpdeck.commands.apply.ApplyService.apply_instance", lambda *args, **kwargs: calls.append("apply")
    )

    result = RUNNER.invoke(app, ["apply", "--instance", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_apply_sudo_reexec_happens_before_original_flow(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.apply")
    monkeypatch.setattr("frpdeck.commands.apply.instance_lock", lambda *args, **kwargs: calls.append("lock"))
    monkeypatch.setattr(
        "frpdeck.commands.apply.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr(
        "frpdeck.commands.apply.ApplyService.apply_instance", lambda *args, **kwargs: calls.append("apply")
    )

    result = RUNNER.invoke(app, ["apply", "--instance", str(tmp_path), "--sudo"])

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_apply_running_as_root_does_not_reexec_sudo(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    def fake_maybe_reexec_with_sudo(**kwargs) -> bool:
        calls.append("reexec")
        return False

    def fake_raise_for_missing_privileges(**kwargs) -> None:
        calls.append("raise")

    def fake_apply_instance(
        self, instance_dir: Path, *, node=None, archive=None, install_if_missing=True, reporter=None
    ):
        calls.append("apply")
        return ApplyExecutionResult(
            ok=True, service_name="client-demo-frpc", config_path=instance_dir / "runtime" / "config" / "frpc.toml"
        )

    monkeypatch.setattr("frpdeck.commands.apply.maybe_reexec_with_sudo", fake_maybe_reexec_with_sudo)
    monkeypatch.setattr("frpdeck.commands.apply.raise_for_missing_privileges", fake_raise_for_missing_privileges)
    monkeypatch.setattr("frpdeck.commands.apply.ApplyService.apply_instance", fake_apply_instance)

    result = RUNNER.invoke(app, ["apply", "--instance", str(tmp_path), "--sudo", "--no-install-if-missing"])

    assert result.exit_code == 0, result.stdout
    assert calls == ["reexec", "raise", "raise", "apply"]


def test_apply_archive_option_uses_explicit_archive(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    _patch_privilege_noop(monkeypatch, "frpdeck.commands.apply")
    archive = tmp_path / "frp_0.65.0_linux_amd64.tar.gz"
    archive.write_text("placeholder", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_apply_instance(
        self, instance_dir: Path, *, node=None, archive=None, install_if_missing=True, reporter=None
    ):
        captured["archive"] = archive
        assert reporter is not None
        reporter.step_started(3, 6, "Ensuring FRP binary is installed...")
        reporter.step_succeeded(f"Installed frpc binary version 0.65.0 from {archive}.")
        return ApplyExecutionResult(
            ok=True,
            service_name="client-demo-frpc",
            binary_version="0.65.0",
            config_path=instance_dir / "runtime" / "config" / "frpc.toml",
        )

    monkeypatch.setattr("frpdeck.commands.apply.ApplyService.apply_instance", fake_apply_instance)

    result = RUNNER.invoke(app, ["apply", "--instance", str(tmp_path), "--archive", str(archive)])

    assert result.exit_code == 0, result.stdout
    assert captured["archive"] == archive.resolve()


def test_proxy_import_writes_config(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    spec_path = tmp_path / "web.yaml"
    spec_path.write_text(
        "name: imported-web\ntype: http\nlocal_port: 8080\ncustom_domains:\n  - imported.example.com\n",
        encoding="utf-8",
    )

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "import",
            str(spec_path),
            "--instance",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = yaml.safe_load((tmp_path / "proxies.yaml").read_text(encoding="utf-8"))
    proxy = next(entry for entry in payload["proxies"] if entry["name"] == "imported-web")
    assert proxy["type"] == "http"
    assert proxy["custom_domains"] == ["imported.example.com"]


def test_proxy_add_tcp_writes_config(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "add",
            "tcp",
            "--instance",
            str(tmp_path),
            "--name",
            "ssh-alt",
            "--local-port",
            "2222",
            "--remote-port",
            "7000",
            "--description",
            "alt ssh",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = yaml.safe_load((tmp_path / "proxies.yaml").read_text(encoding="utf-8"))
    proxy = next(entry for entry in payload["proxies"] if entry["name"] == "ssh-alt")
    assert proxy["type"] == "tcp"
    assert proxy["local_port"] == 2222
    assert proxy["remote_port"] == 7000
    assert proxy["description"] == "alt ssh"


def test_proxy_add_udp_writes_config(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "add",
            "udp",
            "--instance",
            str(tmp_path),
            "--name",
            "dns-alt",
            "--local-port",
            "5353",
            "--remote-port",
            "7001",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = yaml.safe_load((tmp_path / "proxies.yaml").read_text(encoding="utf-8"))
    proxy = next(entry for entry in payload["proxies"] if entry["name"] == "dns-alt")
    assert proxy["type"] == "udp"
    assert proxy["local_port"] == 5353
    assert proxy["remote_port"] == 7001


def test_proxy_add_http_writes_config(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "add",
            "http",
            "--instance",
            str(tmp_path),
            "--name",
            "web",
            "--local-port",
            "8080",
            "--custom-domain",
            "example.com",
            "--custom-domain",
            "www.example.com",
            "--subdomain",
            "app",
            "--description",
            "web app",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = yaml.safe_load((tmp_path / "proxies.yaml").read_text(encoding="utf-8"))
    proxy = next(entry for entry in payload["proxies"] if entry["name"] == "web")
    assert proxy["type"] == "http"
    assert proxy["local_port"] == 8080
    assert proxy["custom_domains"] == ["example.com", "www.example.com"]
    assert proxy["subdomain"] == "app"
    assert proxy["description"] == "web app"


def test_proxy_add_https_writes_config(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "add",
            "https",
            "--instance",
            str(tmp_path),
            "--name",
            "secure-web",
            "--local-port",
            "8443",
            "--custom-domain",
            "secure.example.com",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = yaml.safe_load((tmp_path / "proxies.yaml").read_text(encoding="utf-8"))
    proxy = next(entry for entry in payload["proxies"] if entry["name"] == "secure-web")
    assert proxy["type"] == "https"
    assert proxy["local_port"] == 8443
    assert proxy["custom_domains"] == ["secure.example.com"]
    assert "subdomain" not in proxy


def test_proxy_update_with_positional_patch_file_writes_config(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    patch_path = tmp_path / "web-patch.yaml"
    patch_path.write_text(
        "local_port: 2222\nremote_port: 7002\ndescription: patched ssh\n",
        encoding="utf-8",
    )

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "update",
            "ssh",
            str(patch_path),
            "--instance",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = yaml.safe_load((tmp_path / "proxies.yaml").read_text(encoding="utf-8"))
    proxy = next(entry for entry in payload["proxies"] if entry["name"] == "ssh")
    assert proxy["local_port"] == 2222
    assert proxy["remote_port"] == 7002
    assert proxy["description"] == "patched ssh"


def test_proxy_disable_keeps_definition_and_sets_enabled_false(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = RUNNER.invoke(app, ["proxy", "disable", "ssh", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    payload = yaml.safe_load((tmp_path / "proxies.yaml").read_text(encoding="utf-8"))
    proxy = next(entry for entry in payload["proxies"] if entry["name"] == "ssh")
    assert proxy["enabled"] is False


def test_proxy_remove_permanently_deletes_enabled_and_disabled_definitions(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    enabled_result = RUNNER.invoke(app, ["proxy", "remove", "ssh", "--instance", str(tmp_path)])
    disabled_result = RUNNER.invoke(app, ["proxy", "remove", "dns", "--instance", str(tmp_path)])

    assert enabled_result.exit_code == 0, enabled_result.stdout
    assert disabled_result.exit_code == 0, disabled_result.stdout
    payload = yaml.safe_load((tmp_path / "proxies.yaml").read_text(encoding="utf-8"))
    assert payload["proxies"] == []
    records = _load_audit_records(tmp_path)
    assert [record["target"] for record in records] == [{"proxy_name": "ssh"}, {"proxy_name": "dns"}]


def test_proxy_remove_json_keeps_stable_mutation_envelope(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = RUNNER.invoke(
        app,
        ["proxy", "remove", "ssh", "--instance", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "proxy remove"
    assert payload["data"]["operation"] == "remove"
    assert payload["data"]["changed"] is True
    assert payload["data"]["apply_required"] is True
    assert payload["data"]["removed_name"] == "ssh"
    assert payload["data"]["proxy"] is None


def test_proxy_remove_rejects_removed_hard_option_without_mutation(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    before = (tmp_path / "proxies.yaml").read_text(encoding="utf-8")

    result = RUNNER.invoke(app, ["proxy", "remove", "ssh", "--hard", "--instance", str(tmp_path)])

    assert result.exit_code != 0
    assert (tmp_path / "proxies.yaml").read_text(encoding="utf-8") == before


def test_proxy_add_http_requires_custom_domain_or_subdomain(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    before = (tmp_path / "proxies.yaml").read_text(encoding="utf-8")

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "add",
            "http",
            "--instance",
            str(tmp_path),
            "--name",
            "invalid-web",
            "--local-port",
            "8080",
        ],
    )

    assert result.exit_code == 1, result.stdout
    assert (tmp_path / "proxies.yaml").read_text(encoding="utf-8") == before


def test_proxy_add_https_requires_custom_domain_or_subdomain(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    before = (tmp_path / "proxies.yaml").read_text(encoding="utf-8")

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "add",
            "https",
            "--instance",
            str(tmp_path),
            "--name",
            "invalid-secure-web",
            "--local-port",
            "8443",
        ],
    )

    assert result.exit_code == 1, result.stdout
    assert (tmp_path / "proxies.yaml").read_text(encoding="utf-8") == before


def test_uninstall_fails_fast_with_root_reasons_before_side_effects(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr("frpdeck.commands.uninstall.load_node_config", lambda instance_dir: build_client_node())
    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.uninstall",
        "uninstall requires elevated privileges for this instance:\n- will manage system service via systemctl\nRetry with: frpdeck uninstall --instance x --sudo\nOr run manually: sudo frpdeck uninstall --instance x",
    )
    monkeypatch.setattr(
        "frpdeck.commands.uninstall.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr(
        "frpdeck.commands.uninstall.uninstall_instance", lambda *args, **kwargs: calls.append("uninstall")
    )

    result = RUNNER.invoke(app, ["uninstall", "--instance", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_uninstall_sudo_reexec_happens_before_original_flow(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr("frpdeck.commands.uninstall.load_node_config", lambda instance_dir: build_client_node())
    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.uninstall")
    monkeypatch.setattr(
        "frpdeck.commands.uninstall.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr(
        "frpdeck.commands.uninstall.uninstall_instance", lambda *args, **kwargs: calls.append("uninstall")
    )

    result = RUNNER.invoke(app, ["uninstall", "--instance", str(tmp_path), "--sudo"])

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_uninstall_non_root_without_root_requirement_runs_normally(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr(
        "frpdeck.commands.uninstall.load_node_config",
        lambda instance_dir: build_client_node(overrides={"paths": {"systemd_unit_dir": str(tmp_path / "systemd")}}),
    )
    monkeypatch.setattr(
        "frpdeck.commands.uninstall.analyze_uninstall_root_requirements",
        lambda instance_dir, purge=False, node=None: [],
    )

    def fake_uninstall_instance(instance_dir: Path, purge: bool = False):
        calls.append("uninstall")
        return SimpleNamespace(
            service_name="client-demo-frpc",
            unit_path=tmp_path / "systemd" / "client-demo-frpc.service",
            service_stopped=False,
            service_disabled=False,
            unit_removed=False,
            removed_paths=[],
            kept_paths=[instance_dir],
            warnings=[],
            instance_deleted=False,
        )

    monkeypatch.setattr("frpdeck.commands.uninstall.uninstall_instance", fake_uninstall_instance)

    result = RUNNER.invoke(app, ["uninstall", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert calls == ["uninstall"]


def test_proxy_list_json_returns_envelope() -> None:
    instance = FIXTURE_ROOT / "client-node"

    result = RUNNER.invoke(app, ["proxy", "list", "--instance", str(instance), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "proxy list"
    assert payload["instance"] == str(instance.resolve())
    assert isinstance(payload["data"]["proxies"], list)
    assert payload["data"]["count"] >= 1


def test_proxy_list_json_stays_clean_with_instance_logging_enabled(monkeypatch, tmp_path: Path) -> None:
    instance = tmp_path / "client-node"
    _write_client_instance(
        instance,
        node_overrides={
            "frpdeck_logging": {
                "level": "INFO",
                "stream": "stdout",
                "file_path": "state/logs/frpdeck.log",
            }
        },
    )

    def fake_list_proxies(instance_dir: Path):
        logging.getLogger("frpdeck.test").info("proxy list invoked")
        return []

    monkeypatch.setattr("frpdeck.commands.proxy.MANAGER.list_proxies", fake_list_proxies)

    result = RUNNER.invoke(
        app,
        ["proxy", "list", "--instance", str(instance), "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    log_path = instance / "state" / "logs" / "frpdeck.log"
    assert log_path.is_symlink()
    assert "proxy list invoked" in log_path.resolve().read_text(encoding="utf-8")


def test_proxy_show_json_returns_single_proxy() -> None:
    instance = FIXTURE_ROOT / "client-node"

    result = RUNNER.invoke(app, ["proxy", "show", "--instance", str(instance), "example_ssh_tcp", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "proxy show"
    assert payload["data"]["proxy"]["name"] == "example_ssh_tcp"
    assert payload["data"]["proxy"]["type"] == "tcp"


def test_proxy_preview_json_returns_machine_readable_summary(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "preview",
            "--instance",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "proxy preview"
    assert payload["data"]["enabled_proxies"] == ["ssh"]
    assert payload["data"]["disabled_proxies"] == ["dns"]
    assert payload["data"]["rendered_files"] == ["ssh.toml"]


def test_render_does_not_write_runtime_config(tmp_path: Path) -> None:
    _write_client_instance(tmp_path, node_overrides={"client": {"server_addr": "server.example.com"}})

    result = RUNNER.invoke(app, ["render", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "rendered" / "frpc.toml").exists()
    assert not (tmp_path / "runtime" / "config" / "frpc.toml").exists()


def test_validate_does_not_write_runtime_config(tmp_path: Path) -> None:
    _write_client_instance(tmp_path, node_overrides={"client": {"server_addr": "server.example.com"}})

    result = RUNNER.invoke(app, ["validate", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert not (tmp_path / "runtime" / "config").exists()


def test_sync_command_updates_runtime_config(tmp_path: Path, monkeypatch) -> None:
    _write_client_instance(tmp_path, node_overrides={"client": {"server_addr": "server.example.com"}})
    _write_rendered_client_snapshot(tmp_path, proxy_names=["ssh", "web"])
    _patch_privilege_noop(monkeypatch, "frpdeck.commands.sync")

    result = RUNNER.invoke(app, ["sync", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "runtime" / "config" / "frpc.toml").exists()
    assert (tmp_path / "runtime" / "config" / "proxies.d" / "ssh.toml").exists()
    assert (tmp_path / "runtime" / "config" / "proxies.d" / "web.toml").exists()


def test_sync_command_fails_fast_with_root_reasons_before_side_effects(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.sync",
        "sync requires elevated privileges for this instance:\n- runtime config path is not writable\nRetry with: frpdeck sync --instance x --sudo",
    )
    monkeypatch.setattr("frpdeck.commands.sync.instance_lock", lambda *args, **kwargs: calls.append("lock"))
    monkeypatch.setattr(
        "frpdeck.commands.sync.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr("frpdeck.commands.sync.sync_rendered_to_runtime", lambda *args, **kwargs: calls.append("sync"))

    result = RUNNER.invoke(app, ["sync", "--instance", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_sync_command_sudo_reexec_happens_before_original_flow(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.sync")
    monkeypatch.setattr("frpdeck.commands.sync.instance_lock", lambda *args, **kwargs: calls.append("lock"))
    monkeypatch.setattr(
        "frpdeck.commands.sync.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr("frpdeck.commands.sync.sync_rendered_to_runtime", lambda *args, **kwargs: calls.append("sync"))

    result = RUNNER.invoke(app, ["sync", "--instance", str(tmp_path), "--sudo"])

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_reload_missing_runtime_config_fails_before_command_execution(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path,
        node_overrides={
            "client": {
                "server_addr": "server.example.com",
                "web_server": {"addr": "127.0.0.1", "port": 7400},
            }
        },
    )
    binary_path = tmp_path / "runtime" / "bin" / "frpc"
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_text("binary", encoding="utf-8")
    binary_path.chmod(0o755)
    calls: list[list[str]] = []
    _patch_privilege_noop(monkeypatch, "frpdeck.commands.reload")
    monkeypatch.setattr("frpdeck.commands.reload.run_command", lambda args: calls.append(args))

    result = RUNNER.invoke(app, ["reload", "--instance", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_reload_fails_before_command_execution_when_web_server_disabled(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path,
        node_overrides={
            "client": {
                "server_addr": "server.example.com",
                "web_server": {"enable": False},
            }
        },
    )
    calls: list[list[str]] = []
    _patch_privilege_noop(monkeypatch, "frpdeck.commands.reload")
    monkeypatch.setattr("frpdeck.commands.reload.run_command", lambda args: calls.append(args))

    result = RUNNER.invoke(app, ["reload", "--instance", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_status_json_gracefully_handles_missing_systemctl(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    def fail_status(service_name: str) -> str:
        raise CommandExecutionError("systemctl missing")

    monkeypatch.setattr("frpdeck.services.status_service.status_service", fail_status)

    result = RUNNER.invoke(app, ["status", "--instance", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "status"
    assert payload["data"]["schema_version"] == "frpdeck.status.v1"
    assert payload["warnings"]


def test_status_json_stays_clean_with_instance_logging_enabled(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path,
        node_overrides={
            "frpdeck_logging": {
                "level": "INFO",
                "stream": "stdout",
                "file_path": "state/logs/frpdeck.log",
            }
        },
    )

    def fake_get_instance_status(self, instance_dir: Path) -> InstanceStatus:
        logging.getLogger("frpdeck.test").info("status invoked")
        return InstanceStatus(
            instance=str(instance_dir.resolve()),
            instance_name="client-demo",
            role="client",
            service_name="client-demo-frpc",
            config_summary=ConfigSummary(
                node_config_loaded=True, proxy_config_loaded=True, proxy_total=2, enabled_proxies=1, disabled_proxies=1
            ),
            proxy_counts=ProxyCounts(total=2, enabled=1, disabled=1, by_type={"tcp": 1, "udp": 1}),
            render_summary=RenderSummaryStatus(
                main_config_exists=True,
                rendered_proxy_files=["ssh.toml"],
                rendered_proxy_count=1,
                matches_enabled_proxy_count=True,
            ),
            service_status=ServiceRuntimeStatus(available=True, active=True),
        )

    monkeypatch.setattr("frpdeck.commands.status.StatusService.get_instance_status", fake_get_instance_status)

    result = RUNNER.invoke(app, ["status", "--instance", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "status"
    log_path = tmp_path / "state" / "logs" / "frpdeck.log"
    assert log_path.is_symlink()
    assert "status invoked" in log_path.resolve().read_text(encoding="utf-8")


def test_upgrade_archive_option_uses_explicit_archive(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    archive = tmp_path / "frp_0.65.0_linux_amd64.tar.gz"
    archive.write_text("placeholder", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_install_from_archive(instance_dir: Path, node, archive_path: Path, version_hint: str | None) -> str:
        captured["archive_path"] = archive_path
        return "0.65.0"

    monkeypatch.setattr("frpdeck.commands.upgrade.install_from_archive", fake_install_from_archive)

    result = RUNNER.invoke(app, ["upgrade", "--instance", str(tmp_path), "--archive", str(archive), "--no-restart"])

    assert result.exit_code == 0, result.stdout
    assert captured["archive_path"] == archive.resolve()


def test_mcp_install_stdio_wrapper_creates_executable_script(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])

    script_path = tmp_path / WRAPPER_FILENAME
    assert result.exit_code == 0, result.stdout
    assert script_path.exists()
    assert script_path.stat().st_mode & 0o111
    content = script_path.read_text(encoding="utf-8")
    assert f"INSTANCE_DIR={tmp_path.resolve()}" in content
    assert '"$PYTHON_BIN" -m frpdeck.mcp.server --instance-dir "$INSTANCE_DIR"' in content
    assert f"PYTHON_BIN={Path(sys.executable).resolve()}" in content
    assert 'if [[ ! -x "$PYTHON_BIN" ]]; then' in content
    assert "frpdeck MCP wrapper error: failed to start the bound stdio MCP server." in content
    assert "This wrapper starts the frpdeck stdio MCP server for one bound instance." in content
    assert "source .venv/bin/activate" not in content
    assert "exec python -m frpdeck.mcp.server" not in content
    assert str(Path(sys.executable).resolve()) in content
    records = _load_audit_records(tmp_path)
    assert records[0]["operation"] == "mcp_wrapper_install"
    assert records[0]["target"]["wrapper_path"] == str(script_path.resolve())
    assert records[0]["target"]["instance_dir"] == str(tmp_path.resolve())


def test_mcp_install_stdio_wrapper_rejects_empty_directory_without_side_effects(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 1
    assert not (tmp_path / WRAPPER_FILENAME).exists()
    assert not (tmp_path / "state").exists()


def test_mcp_install_stdio_wrapper_ssh_host_does_not_change_wrapper(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    local_result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])
    script_path = tmp_path / WRAPPER_FILENAME
    local_content = script_path.read_text(encoding="utf-8")

    remote_result = RUNNER.invoke(
        app,
        [
            "mcp",
            "install-stdio-wrapper",
            "--instance",
            str(tmp_path),
            "--ssh-host",
            "example-host",
        ],
    )

    assert local_result.exit_code == 0, local_result.output
    assert remote_result.exit_code == 0, remote_result.output
    assert script_path.read_text(encoding="utf-8") == local_content


def test_mcp_install_stdio_wrapper_defaults_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper"])

    script_path = tmp_path / WRAPPER_FILENAME
    assert result.exit_code == 0, result.stdout
    assert script_path.exists()
    content = script_path.read_text(encoding="utf-8")
    assert f"INSTANCE_DIR={tmp_path.resolve()}" in content


def test_mcp_install_stdio_wrapper_allows_python_override(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    fake_python = tmp_path / "bin" / "python-custom"
    fake_python.parent.mkdir(parents=True, exist_ok=True)
    fake_python.write_text("", encoding="utf-8")
    fake_python.chmod(0o755)

    result = RUNNER.invoke(
        app,
        ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path), "--python", str(fake_python)],
    )

    script_path = tmp_path / WRAPPER_FILENAME
    assert result.exit_code == 0, result.stdout
    content = script_path.read_text(encoding="utf-8")
    assert f"PYTHON_BIN={fake_python.resolve()}" in content


def test_mcp_install_stdio_wrapper_ignores_virtual_env_for_default_python(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    venv_python = tmp_path / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    venv_python.chmod(0o755)
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "venv"))

    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    content = (tmp_path / WRAPPER_FILENAME).read_text(encoding="utf-8")
    assert f"PYTHON_BIN={Path(sys.executable).resolve()}" in content


def test_mcp_install_stdio_wrapper_python_override_wins_over_virtual_env(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    venv_python = tmp_path / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    venv_python.chmod(0o755)
    fake_python = tmp_path / "bin" / "python-custom"
    fake_python.parent.mkdir(parents=True, exist_ok=True)
    fake_python.write_text("", encoding="utf-8")
    fake_python.chmod(0o755)
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "venv"))

    result = RUNNER.invoke(
        app,
        ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path), "--python", str(fake_python)],
    )

    assert result.exit_code == 0, result.stdout
    content = (tmp_path / WRAPPER_FILENAME).read_text(encoding="utf-8")
    assert f"PYTHON_BIN={fake_python.resolve()}" in content


def test_mcp_uninstall_stdio_wrapper_removes_script(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    script_path = tmp_path / WRAPPER_FILENAME
    RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])
    (tmp_path / "node.yaml").unlink()

    result = RUNNER.invoke(app, ["mcp", "uninstall-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert not script_path.exists()
    records = _load_audit_records(tmp_path)
    assert records[-1]["operation"] == "mcp_wrapper_uninstall"
    assert records[-1]["after"]["exists"] is False


def test_mcp_uninstall_stdio_wrapper_is_not_fatal_when_missing(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["mcp", "uninstall-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    records = _load_audit_records(tmp_path)
    assert records[-1]["operation"] == "mcp_wrapper_uninstall"
    assert records[-1]["before"]["exists"] is False
    assert records[-1]["after"]["exists"] is False


def test_mcp_uninstall_stdio_wrapper_defaults_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    monkeypatch.chdir(tmp_path)
    RUNNER.invoke(app, ["mcp", "install-stdio-wrapper"])

    result = RUNNER.invoke(app, ["mcp", "uninstall-stdio-wrapper"])

    assert result.exit_code == 0, result.stdout
    assert not (tmp_path / WRAPPER_FILENAME).exists()


def test_restart_fails_fast_with_root_reasons_before_side_effects(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.restart",
        "restart requires elevated privileges for this instance:\n- will manage system service via systemctl\nRetry with: frpdeck restart --instance x --sudo\nOr run manually: sudo frpdeck restart --instance x",
    )
    monkeypatch.setattr(
        "frpdeck.commands.restart.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr("frpdeck.commands.restart.restart_service", lambda *args, **kwargs: calls.append("restart"))

    result = RUNNER.invoke(app, ["restart", "--instance", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_restart_sudo_reexec_happens_before_original_flow(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.restart")
    monkeypatch.setattr(
        "frpdeck.commands.restart.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr("frpdeck.commands.restart.restart_service", lambda *args, **kwargs: calls.append("restart"))

    result = RUNNER.invoke(app, ["restart", "--instance", str(tmp_path), "--sudo"])

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_reload_fails_fast_with_root_reasons_before_command_execution(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path,
        node_overrides={
            "client": {
                "server_addr": "server.example.com",
                "web_server": {"addr": "127.0.0.1", "port": 7400},
            }
        },
    )
    calls: list[str] = []

    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.reload",
        "reload requires elevated privileges for this instance:\n- frpc binary is not executable by current user: /tmp/x\nRetry with: frpdeck reload --instance x --sudo\nOr run manually: sudo frpdeck reload --instance x",
    )
    monkeypatch.setattr(
        "frpdeck.commands.reload.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr("frpdeck.commands.reload.run_command", lambda *args, **kwargs: calls.append("reload"))

    result = RUNNER.invoke(app, ["reload", "--instance", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_reload_sudo_reexec_happens_before_original_flow(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.reload")
    monkeypatch.setattr(
        "frpdeck.commands.reload.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr("frpdeck.commands.reload.run_command", lambda *args, **kwargs: calls.append("reload"))

    result = RUNNER.invoke(app, ["reload", "--instance", str(tmp_path), "--sudo"])

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_upgrade_fails_fast_with_root_reasons_before_side_effects(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.upgrade",
        "upgrade requires elevated privileges for this instance:\n- install path is not writable by current user: /tmp/x\nRetry with: frpdeck upgrade --instance x --sudo\nOr run manually: sudo frpdeck upgrade --instance x",
    )
    monkeypatch.setattr("frpdeck.commands.upgrade.instance_lock", lambda *args, **kwargs: calls.append("lock"))
    monkeypatch.setattr(
        "frpdeck.commands.upgrade.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr(
        "frpdeck.commands.upgrade.install_from_archive", lambda *args, **kwargs: calls.append("archive")
    )
    monkeypatch.setattr(
        "frpdeck.commands.upgrade.install_from_release", lambda *args, **kwargs: calls.append("release")
    )

    result = RUNNER.invoke(app, ["upgrade", "--instance", str(tmp_path), "--no-restart"])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_upgrade_sudo_reexec_happens_before_original_flow(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.upgrade")
    monkeypatch.setattr("frpdeck.commands.upgrade.instance_lock", lambda *args, **kwargs: calls.append("lock"))
    monkeypatch.setattr(
        "frpdeck.commands.upgrade.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr(
        "frpdeck.commands.upgrade.install_from_archive", lambda *args, **kwargs: calls.append("archive")
    )
    monkeypatch.setattr(
        "frpdeck.commands.upgrade.install_from_release", lambda *args, **kwargs: calls.append("release")
    )

    result = RUNNER.invoke(app, ["upgrade", "--instance", str(tmp_path), "--sudo", "--no-restart"])

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_init_fails_fast_with_root_reasons_before_scaffold(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.init",
        "init requires elevated privileges for the target directory:\n- target instance directory is not creatable by current user: /tmp/x\nRetry with: frpdeck init client demo --directory /tmp/x --sudo\nOr run manually: sudo frpdeck init client demo --directory /tmp/x",
    )
    monkeypatch.setattr("frpdeck.commands.init.scaffold_instance", lambda *args, **kwargs: calls.append("scaffold"))

    result = RUNNER.invoke(app, ["init", "client", "demo", "--directory", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_init_sudo_reexec_happens_before_scaffold(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.init")
    monkeypatch.setattr("frpdeck.commands.init.scaffold_instance", lambda *args, **kwargs: calls.append("scaffold"))

    result = RUNNER.invoke(app, ["init", "client", "demo", "--directory", str(tmp_path), "--sudo"])

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_render_fails_fast_with_root_reasons_before_rendering(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.render",
        "render requires elevated privileges for this instance:\n- rendered output path is not writable by current user: /tmp/x\nRetry with: frpdeck render --instance x --sudo\nOr run manually: sudo frpdeck render --instance x",
    )
    monkeypatch.setattr(
        "frpdeck.commands.render.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr("frpdeck.commands.render.render_instance", lambda *args, **kwargs: calls.append("render"))

    result = RUNNER.invoke(app, ["render", "--instance", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_render_sudo_reexec_happens_before_rendering(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.render")
    monkeypatch.setattr(
        "frpdeck.commands.render.instance_logging_context", lambda *args, **kwargs: calls.append("logging")
    )
    monkeypatch.setattr("frpdeck.commands.render.render_instance", lambda *args, **kwargs: calls.append("render"))

    result = RUNNER.invoke(app, ["render", "--instance", str(tmp_path), "--sudo"])

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_proxy_add_tcp_fails_fast_with_root_reasons_before_mutation(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    calls: list[str] = []

    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.proxy",
        "proxy add tcp requires elevated privileges for this instance:\n- proxy config is not writable by current user: /tmp/x\nRetry with: frpdeck proxy add tcp --instance x --sudo\nOr run manually: sudo frpdeck proxy add tcp --instance x",
    )
    monkeypatch.setattr("frpdeck.commands.proxy.MANAGER.add_proxy", lambda *args, **kwargs: calls.append("add"))

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "add",
            "tcp",
            "--instance",
            str(tmp_path),
            "--name",
            "ssh-alt",
            "--local-port",
            "2222",
            "--remote-port",
            "7000",
        ],
    )

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_proxy_add_tcp_sudo_reexec_happens_before_mutation(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.proxy")
    monkeypatch.setattr("frpdeck.commands.proxy.MANAGER.add_proxy", lambda *args, **kwargs: calls.append("add"))

    result = RUNNER.invoke(
        app,
        [
            "proxy",
            "add",
            "tcp",
            "--instance",
            str(tmp_path),
            "--name",
            "ssh-alt",
            "--local-port",
            "2222",
            "--remote-port",
            "7000",
            "--sudo",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_mcp_install_stdio_wrapper_fails_fast_with_root_reasons_before_mutation(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    _patch_privilege_fail(
        monkeypatch,
        "frpdeck.commands.mcp",
        "mcp install-stdio-wrapper requires elevated privileges for this instance:\n- wrapper path is not writable by current user: /tmp/x\nRetry with: frpdeck mcp install-stdio-wrapper --instance x --sudo\nOr run manually: sudo frpdeck mcp install-stdio-wrapper --instance x",
    )
    monkeypatch.setattr("frpdeck.commands.mcp.instance_lock", lambda *args, **kwargs: calls.append("lock"))
    monkeypatch.setattr("frpdeck.commands.mcp._write_wrapper_script", lambda *args, **kwargs: calls.append("write"))

    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 1, result.stdout
    assert calls == []


def test_mcp_install_stdio_wrapper_sudo_reexec_happens_before_mutation(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    _patch_privilege_reexec(monkeypatch, "frpdeck.commands.mcp")
    monkeypatch.setattr("frpdeck.commands.mcp.instance_lock", lambda *args, **kwargs: calls.append("lock"))
    monkeypatch.setattr("frpdeck.commands.mcp._write_wrapper_script", lambda *args, **kwargs: calls.append("write"))

    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path), "--sudo"])

    assert result.exit_code == 0, result.stdout
    assert calls == []


def test_mcp_install_stdio_wrapper_surfaces_audit_failure_as_warning(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    warnings: list[str] = []
    monkeypatch.setattr(
        "frpdeck.commands.mcp.record_audit_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr("frpdeck.commands.mcp.echo_warning", warnings.append)

    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / WRAPPER_FILENAME).exists()
    assert warnings == ["audit log append failed: disk full"]


def test_audit_recent_defaults_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    monkeypatch.chdir(tmp_path)
    RUNNER.invoke(app, ["mcp", "install-stdio-wrapper"])

    result = RUNNER.invoke(app, ["audit", "recent", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["data"]["count"] == 1
    assert payload["data"]["entries"][0]["operation"] == "mcp_wrapper_install"


def test_audit_recent_json_returns_entries(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])
    RUNNER.invoke(app, ["mcp", "uninstall-stdio-wrapper", "--instance", str(tmp_path)])

    result = RUNNER.invoke(app, ["audit", "recent", "--instance", str(tmp_path), "--limit", "2", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "audit recent"
    assert payload["data"]["count"] == 2
    assert isinstance(payload["data"]["entries"], list)
    assert payload["data"]["entries"][0]["operation"] == "mcp_wrapper_uninstall"


def test_audit_recent_handles_missing_audit_file(tmp_path: Path) -> None:
    json_result = RUNNER.invoke(app, ["audit", "recent", "--instance", str(tmp_path), "--json"])

    assert json_result.exit_code == 0, json_result.stdout
    payload = json.loads(json_result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["count"] == 0
    assert payload["data"]["entries"] == []
