from pathlib import Path
import json
import logging
import shutil
import sys
from types import SimpleNamespace

from typer.testing import CliRunner
import yaml

from frpdeck.cli import app
from frpdeck.commands.mcp import WRAPPER_FILENAME
from frpdeck.domain.errors import CommandExecutionError
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.status_models import ConfigSummary, InstanceStatus, ProxyCounts, RenderSummaryStatus, ServiceRuntimeStatus
from frpdeck.domain.proxy_management import ApplyReport
from frpdeck.services.apply_service import ApplyExecutionResult
from frpdeck.storage.dump import dump_yaml_model
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


def _copy_fixture_instance(name: str, destination: Path) -> Path:
    instance_dir = destination / name
    shutil.copytree(FIXTURE_ROOT / name, instance_dir)
    return instance_dir


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
    assert node_payload["frpdeck_logging"]["file_path"] == "state/logs/frpdeck.log"
    assert node_payload["frpdeck_logging"]["stream"] == "stderr"
    assert node_payload["service"]["service_name"] == "frpdeck-demo-node-frpc"
    assert proxies_payload["proxies"][0]["name"] == "sample_tcp"
    assert (tmp_path / "demo-node" / "secrets" / "token.txt.example").read_text(encoding="utf-8") == "PLEASE_FILL_TOKEN\n"


def test_init_server_skips_proxy_file(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["init", "server", "demo-node", "--directory", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "demo-node" / "node.yaml").exists()
    assert not (tmp_path / "demo-node" / "proxies.yaml").exists()
    assert (tmp_path / "demo-node" / "secrets" / "token.txt.example").exists()
    node_payload = yaml.safe_load((tmp_path / "demo-node" / "node.yaml").read_text(encoding="utf-8"))
    assert node_payload["server"]["subdomain_host"] == "PLEASE_FILL_DOMAIN"
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
    assert "proxy includes: 0" in render_result.stdout

    validate_result = RUNNER.invoke(app, ["validate", "--instance", str(tmp_path)])

    assert validate_result.exit_code == 0, validate_result.stdout
    assert "validation passed" in validate_result.stdout


def test_validate_reports_placeholder_errors() -> None:
    instance = FIXTURE_ROOT / "client-node"

    result = RUNNER.invoke(app, ["validate", "--instance", str(instance)])

    assert result.exit_code == 1
    assert "client.server_addr still uses a placeholder value" in result.stdout


def test_version_option_returns_success() -> None:
    result = RUNNER.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip()


def test_root_command_without_args_shows_help() -> None:
    result = RUNNER.invoke(app, [])

    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert "apply" in result.stdout
    assert "status" in result.stdout


def test_apply_shows_human_readable_step_output(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    def fake_apply_instance(self, instance_dir: Path, *, node=None, archive=None, install_if_missing=True, reporter=None):
        assert reporter is not None
        assert install_if_missing is False
        reporter.step_started(1, 6, "Validating instance configuration...")
        reporter.step_succeeded("Validation passed.")
        reporter.step_started(2, 6, "Rendering configuration files...")
        reporter.step_succeeded(f"Rendered files under {instance_dir / 'rendered'}.")
        reporter.step_started(3, 6, "Ensuring FRP binary is installed...")
        reporter.step_skipped("Binary installation skipped by --no-install-if-missing.")
        reporter.step_started(4, 6, "Syncing rendered files into runtime directories...")
        reporter.step_succeeded(f"Updated FRP runtime config at {instance_dir / 'runtime' / 'config' / 'frpc.toml'}.")
        reporter.step_started(5, 6, "Installing/updating systemd unit...")
        reporter.step_succeeded(f"Installed unit at {instance_dir / 'units' / 'client-demo-frpc.service'}.")
        reporter.step_started(6, 6, "Reloading systemd and restarting service...")
        reporter.step_succeeded("Service client-demo-frpc is enabled and restarted.")
        return ApplyExecutionResult(
            ok=True,
            service_name="client-demo-frpc",
            config_path=instance_dir / "runtime" / "config" / "frpc.toml",
        )

    monkeypatch.setattr("frpdeck.commands.apply.ApplyService.apply_instance", fake_apply_instance)

    result = RUNNER.invoke(app, ["apply", "--instance", str(tmp_path), "--no-install-if-missing"])

    assert result.exit_code == 0, result.stdout
    assert "[1/6] Validating instance configuration..." in result.stdout
    assert "[2/6] Rendering configuration files..." in result.stdout
    assert "[3/6] Ensuring FRP binary is installed..." in result.stdout
    assert "Binary installation skipped by --no-install-if-missing." in result.stdout
    assert "[4/6] Syncing rendered files into runtime directories..." in result.stdout
    assert "[5/6] Installing/updating systemd unit..." in result.stdout
    assert "[6/6] Reloading systemd and restarting service..." in result.stdout
    assert "Apply completed successfully." in result.stdout


def test_apply_archive_option_uses_explicit_archive(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)
    archive = tmp_path / "frp_0.65.0_linux_amd64.tar.gz"
    archive.write_text("placeholder", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_apply_instance(self, instance_dir: Path, *, node=None, archive=None, install_if_missing=True, reporter=None):
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
    assert f"Installed frpc binary version 0.65.0 from {archive.resolve()}." in result.stdout


def test_apply_shows_download_progress_during_release_install(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    def fake_apply_instance(self, instance_dir: Path, *, node=None, archive=None, install_if_missing=True, reporter=None):
        assert reporter is not None
        assert archive is None
        reporter.download_started("frp_0.65.0_linux_amd64.tar.gz")
        reporter.download_progress(1_048_576, 2_097_152)
        reporter.download_progress(2_097_152, 2_097_152)
        reporter.download_finished("frp_0.65.0_linux_amd64.tar.gz")
        return ApplyExecutionResult(
            ok=True,
            service_name="client-demo-frpc",
            binary_version="0.65.0",
            config_path=instance_dir / "runtime" / "config" / "frpc.toml",
        )

    monkeypatch.setattr("frpdeck.commands.apply.ApplyService.apply_instance", fake_apply_instance)

    result = RUNNER.invoke(app, ["apply", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "Downloading frp_0.65.0_linux_amd64.tar.gz..." in result.stdout
    assert "Download progress: 50% (1.0 MiB / 2.0 MiB)" in result.stdout
    assert "Download progress: 100% (2.0 MiB / 2.0 MiB)" in result.stdout
    assert "OK: Downloaded frp_0.65.0_linux_amd64.tar.gz." in result.stdout


def test_proxy_list_succeeds_on_example_instance() -> None:
    instance = FIXTURE_ROOT / "client-node"

    result = RUNNER.invoke(app, ["proxy", "list", "--instance", str(instance)])

    assert result.exit_code == 0, result.stdout
    assert "example_web_http" in result.stdout


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
    assert result.stdout.strip().startswith("{")


def test_proxy_show_json_returns_single_proxy() -> None:
    instance = FIXTURE_ROOT / "client-node"

    result = RUNNER.invoke(app, ["proxy", "show", "--instance", str(instance), "example_ssh_tcp", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "proxy show"
    assert payload["data"]["proxy"]["name"] == "example_ssh_tcp"
    assert payload["data"]["proxy"]["type"] == "tcp"


def test_proxy_validate_json_error_returns_pure_json() -> None:
    instance = FIXTURE_ROOT / "client-node"

    result = RUNNER.invoke(app, ["proxy", "validate", "--instance", str(instance), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "proxy validate"
    assert payload["data"]["error_count"] >= 1
    assert payload["errors"]
    assert result.stdout.strip().startswith("{")


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


def test_proxy_apply_json_returns_envelope_with_mocked_manager(monkeypatch) -> None:
    instance = FIXTURE_ROOT / "client-node"

    class FakeProxy:
        def __init__(self, name: str, enabled: bool) -> None:
            self.name = name
            self.enabled = enabled

    def fake_list_proxies(instance_dir: Path):
        return [FakeProxy("ssh", True), FakeProxy("dns", False)]

    monkeypatch.setattr("frpdeck.commands.proxy.MANAGER.list_proxies", fake_list_proxies)
    monkeypatch.setattr(
        "frpdeck.commands.proxy.MANAGER.apply_proxy_changes",
        lambda instance_dir, reload=True: ApplyReport(
            ok=True,
            step="reload",
            errors=[],
            warnings=[],
            rendered_proxy_files=["ssh.toml"],
            reload_requested=reload,
            reloaded=reload,
            reload_output="reload completed",
        ),
    )

    result = RUNNER.invoke(app, ["proxy", "apply", "--instance", str(instance), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "proxy apply"
    assert payload["data"]["reloaded"] is True
    assert payload["data"]["rendered_files"] == ["ssh.toml"]
    assert payload["data"]["applied_proxies"] == ["ssh"]


def test_proxy_apply_json_rejects_server_instance(tmp_path: Path) -> None:
    _write_server_instance(tmp_path)

    result = RUNNER.invoke(app, ["proxy", "apply", "--instance", str(tmp_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "proxy apply"
    assert payload["errors"]


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
            config_summary=ConfigSummary(node_config_loaded=True, proxy_config_loaded=True, proxy_total=2, enabled_proxies=1, disabled_proxies=1),
            proxy_counts=ProxyCounts(total=2, enabled=1, disabled=1, by_type={"tcp": 1, "udp": 1}),
            render_summary=RenderSummaryStatus(main_config_exists=True, rendered_proxy_files=["ssh.toml"], rendered_proxy_count=1, matches_enabled_proxy_count=True),
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
    assert result.stdout.strip().startswith("{")


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
    assert "upgraded to 0.65.0" in result.stdout


def test_upgrade_shows_download_progress_for_release_install(monkeypatch, tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    monkeypatch.setattr(
        "frpdeck.commands.upgrade.get_release",
        lambda binary: SimpleNamespace(asset_name="frp_0.65.0_linux_amd64.tar.gz"),
    )

    def fake_install_from_release(instance_dir: Path, node, release, *, progress=None, download_started=None, download_finished=None) -> str:
        download_started(release.asset_name)
        progress(1_048_576, 2_097_152)
        progress(2_097_152, 2_097_152)
        download_finished(release.asset_name)
        return "0.65.0"

    monkeypatch.setattr("frpdeck.commands.upgrade.install_from_release", fake_install_from_release)

    result = RUNNER.invoke(app, ["upgrade", "--instance", str(tmp_path), "--no-restart"])

    assert result.exit_code == 0, result.stdout
    assert "Downloading frp_0.65.0_linux_amd64.tar.gz..." in result.stdout
    assert "Download progress: 50% (1.0 MiB / 2.0 MiB)" in result.stdout
    assert "Download progress: 100% (2.0 MiB / 2.0 MiB)" in result.stdout
    assert "OK: Downloaded frp_0.65.0_linux_amd64.tar.gz." in result.stdout
    assert "upgraded to 0.65.0" in result.stdout


def test_mcp_install_stdio_wrapper_creates_executable_script(tmp_path: Path) -> None:
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
    assert 'frpdeck MCP wrapper error: failed to start the bound stdio MCP server.' in content
    assert "This wrapper starts the frpdeck stdio MCP server for one bound instance." in content
    assert "source .venv/bin/activate" not in content
    assert "exec python -m frpdeck.mcp.server" not in content
    assert str(Path(sys.executable).resolve()) in content
    assert f"Wrapper path: {script_path.resolve()}" in result.stdout
    assert f"Bound instance: {tmp_path.resolve()}" in result.stdout
    assert f"Python: {Path(sys.executable).resolve()}" in result.stdout
    assert "Claude Code example:" in result.stdout
    assert str(script_path.resolve()) in result.stdout
    assert "Please manually verify the SSH command first before enabling BatchMode yes." in result.stdout
    assert "If this wrapper fails remotely, verify that the embedded Python interpreter is valid in that environment." in result.stdout
    records = _load_audit_records(tmp_path)
    assert records[0]["operation"] == "mcp_wrapper_install"
    assert records[0]["target"]["wrapper_path"] == str(script_path.resolve())
    assert records[0]["target"]["instance_dir"] == str(tmp_path.resolve())


def test_mcp_install_stdio_wrapper_defaults_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper"])

    script_path = tmp_path / WRAPPER_FILENAME
    assert result.exit_code == 0, result.stdout
    assert script_path.exists()
    content = script_path.read_text(encoding="utf-8")
    assert f"INSTANCE_DIR={tmp_path.resolve()}" in content
    assert f"Bound instance: {tmp_path.resolve()}" in result.stdout


def test_mcp_install_stdio_wrapper_allows_python_override(tmp_path: Path) -> None:
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
    assert f"Python: {fake_python.resolve()}" in result.stdout


def test_mcp_install_stdio_wrapper_ignores_virtual_env_for_default_python(monkeypatch, tmp_path: Path) -> None:
    venv_python = tmp_path / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    venv_python.chmod(0o755)
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "venv"))

    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    content = (tmp_path / WRAPPER_FILENAME).read_text(encoding="utf-8")
    assert f"PYTHON_BIN={Path(sys.executable).resolve()}" in content
    assert f"Python: {Path(sys.executable).resolve()}" in result.stdout


def test_mcp_install_stdio_wrapper_python_override_wins_over_virtual_env(monkeypatch, tmp_path: Path) -> None:
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
    assert f"Python: {fake_python.resolve()}" in result.stdout


def test_mcp_uninstall_stdio_wrapper_removes_script(tmp_path: Path) -> None:
    script_path = tmp_path / WRAPPER_FILENAME
    RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])

    result = RUNNER.invoke(app, ["mcp", "uninstall-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert not script_path.exists()
    assert "Removed stdio wrapper" in result.stdout
    records = _load_audit_records(tmp_path)
    assert records[-1]["operation"] == "mcp_wrapper_uninstall"
    assert records[-1]["after"]["exists"] is False


def test_mcp_uninstall_stdio_wrapper_is_not_fatal_when_missing(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["mcp", "uninstall-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "already absent" in result.stdout


def test_mcp_uninstall_stdio_wrapper_defaults_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    RUNNER.invoke(app, ["mcp", "install-stdio-wrapper"])

    result = RUNNER.invoke(app, ["mcp", "uninstall-stdio-wrapper"])

    assert result.exit_code == 0, result.stdout
    assert not (tmp_path / WRAPPER_FILENAME).exists()


def test_audit_recent_text_shows_latest_entries(tmp_path: Path) -> None:
    RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])
    RUNNER.invoke(app, ["mcp", "uninstall-stdio-wrapper", "--instance", str(tmp_path)])

    result = RUNNER.invoke(app, ["audit", "recent", "--instance", str(tmp_path), "--limit", "1"])

    assert result.exit_code == 0, result.stdout
    assert "mcp_wrapper_uninstall" in result.stdout
    assert "source=cli" in result.stdout


def test_audit_recent_defaults_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    RUNNER.invoke(app, ["mcp", "install-stdio-wrapper"])

    result = RUNNER.invoke(app, ["audit", "recent"])

    assert result.exit_code == 0, result.stdout
    assert "mcp_wrapper_install" in result.stdout


def test_audit_recent_json_returns_entries(tmp_path: Path) -> None:
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
    text_result = RUNNER.invoke(app, ["audit", "recent", "--instance", str(tmp_path)])
    json_result = RUNNER.invoke(app, ["audit", "recent", "--instance", str(tmp_path), "--json"])

    assert text_result.exit_code == 0, text_result.stdout
    assert "no audit log found" in text_result.stdout
    payload = json.loads(json_result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["count"] == 0
    assert payload["data"]["entries"] == []


def test_mcp_command_group_is_available() -> None:
    result = RUNNER.invoke(app, ["mcp", "--help"])

    assert result.exit_code == 0, result.stdout
    assert "install-stdio-wrapper" in result.stdout
    assert "uninstall-stdio-wrapper" in result.stdout


def test_audit_command_group_is_available() -> None:
    result = RUNNER.invoke(app, ["audit", "--help"])

    assert result.exit_code == 0, result.stdout
    assert "recent" in result.stdout
