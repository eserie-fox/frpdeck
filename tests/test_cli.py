from pathlib import Path
import json
import shutil
import sys
from types import SimpleNamespace

from typer.testing import CliRunner

from frpdeck.cli import app
from frpdeck.commands.mcp import WRAPPER_FILENAME
from frpdeck.domain.client_config import AuthConfig, ClientCommonConfig
from frpdeck.domain.errors import CommandExecutionError
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.proxy_management import ApplyReport
from frpdeck.domain.server_config import ServerCommonConfig
from frpdeck.domain.state import ClientNodeConfig, ServerNodeConfig
from frpdeck.domain.systemd import ServiceConfig
from frpdeck.storage.dump import dump_yaml_model


RUNNER = CliRunner()
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "instances"


def _load_audit_records(instance_dir: Path) -> list[dict[str, object]]:
    audit_path = instance_dir / "state" / "audit" / "audit.jsonl"
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


def _copy_fixture_instance(name: str, destination: Path) -> Path:
    instance_dir = destination / name
    shutil.copytree(FIXTURE_ROOT / name, instance_dir)
    return instance_dir


def test_init_creates_base_files(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["init", "client", "demo-node", "--directory", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "demo-node" / "node.yaml").exists()
    assert (tmp_path / "demo-node" / "proxies.yaml").exists()
    assert (tmp_path / "demo-node" / "secrets" / "token.txt.example").exists()


def test_render_succeeds_on_example_instance(tmp_path: Path) -> None:
    instance = _copy_fixture_instance("client-node", tmp_path)

    assert not (instance / "rendered" / "frpc.toml").exists()

    result = RUNNER.invoke(app, ["render", "--instance", str(instance)])

    assert result.exit_code == 0, result.stdout
    assert (instance / "rendered" / "frpc.toml").exists()
    assert (instance / "rendered" / "proxies.d" / "example_web_http.toml").exists()
    assert (instance / "rendered" / "proxies.d" / "example_ssh_tcp.toml").exists()


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

    monkeypatch.setattr("frpdeck.commands.apply.validate_instance", lambda instance_dir, node, proxies: [])
    monkeypatch.setattr(
        "frpdeck.commands.apply.render_instance",
        lambda instance_dir, node, proxies: SimpleNamespace(systemd_unit_path=instance_dir / "rendered" / "demo.service"),
    )
    monkeypatch.setattr("frpdeck.commands.apply.sync_rendered_to_runtime", lambda instance_dir, node: instance_dir / "runtime" / "config" / "frpc.toml")
    monkeypatch.setattr("frpdeck.commands.apply.install_unit", lambda rendered_unit, target_unit: None)
    monkeypatch.setattr("frpdeck.commands.apply.daemon_reload", lambda: None)
    monkeypatch.setattr("frpdeck.commands.apply.enable_service", lambda service_name: None)
    monkeypatch.setattr("frpdeck.commands.apply.restart_service", lambda service_name: None)

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


def test_mcp_install_stdio_wrapper_prefers_virtual_env_python(monkeypatch, tmp_path: Path) -> None:
    venv_python = tmp_path / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    venv_python.chmod(0o755)
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "venv"))

    result = RUNNER.invoke(app, ["mcp", "install-stdio-wrapper", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    content = (tmp_path / WRAPPER_FILENAME).read_text(encoding="utf-8")
    assert f"PYTHON_BIN={venv_python.resolve()}" in content
    assert f"Python: {venv_python.resolve()}" in result.stdout


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

