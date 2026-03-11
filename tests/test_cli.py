from pathlib import Path
import json

from typer.testing import CliRunner

from frpdeck.cli import app
from frpdeck.domain.client_config import AuthConfig, ClientCommonConfig
from frpdeck.domain.errors import CommandExecutionError
from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.proxy_management import ApplyReport
from frpdeck.domain.server_config import ServerCommonConfig
from frpdeck.domain.state import ClientNodeConfig, ServerNodeConfig
from frpdeck.domain.systemd import ServiceConfig
from frpdeck.storage.dump import dump_yaml_model


RUNNER = CliRunner()


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


def test_init_creates_base_files(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["init", "client", "demo-node", "--directory", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "demo-node" / "node.yaml").exists()
    assert (tmp_path / "demo-node" / "proxies.yaml").exists()
    assert (tmp_path / "demo-node" / "secrets" / "token.txt.example").exists()


def test_render_succeeds_on_example_instance() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    instance = repo_root / "examples" / "client-node"

    result = RUNNER.invoke(app, ["render", "--instance", str(instance)])

    assert result.exit_code == 0, result.stdout
    assert (instance / "rendered" / "frpc.toml").exists()


def test_validate_reports_placeholder_errors() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    instance = repo_root / "examples" / "client-node"

    result = RUNNER.invoke(app, ["validate", "--instance", str(instance)])

    assert result.exit_code == 1
    assert "client.server_addr still uses a placeholder value" in result.stdout


def test_version_option_returns_success() -> None:
    result = RUNNER.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip()


def test_proxy_list_succeeds_on_example_instance() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    instance = repo_root / "examples" / "client-node"

    result = RUNNER.invoke(app, ["proxy", "list", "--instance", str(instance)])

    assert result.exit_code == 0, result.stdout
    assert "grape_web_http" in result.stdout


def test_proxy_list_json_returns_envelope() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    instance = repo_root / "examples" / "client-node"

    result = RUNNER.invoke(app, ["proxy", "list", "--instance", str(instance), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "proxy list"
    assert payload["instance"] == str(instance.resolve())
    assert isinstance(payload["data"]["proxies"], list)
    assert payload["data"]["count"] >= 1


def test_proxy_show_json_returns_single_proxy() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    instance = repo_root / "examples" / "client-node"

    result = RUNNER.invoke(app, ["proxy", "show", "--instance", str(instance), "grape_ssh_tcp", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "proxy show"
    assert payload["data"]["proxy"]["name"] == "grape_ssh_tcp"
    assert payload["data"]["proxy"]["type"] == "tcp"


def test_proxy_validate_json_error_returns_pure_json() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    instance = repo_root / "examples" / "client-node"

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
    repo_root = Path(__file__).resolve().parents[1]
    instance = repo_root / "examples" / "client-node"

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

