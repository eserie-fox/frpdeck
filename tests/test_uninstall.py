from pathlib import Path


from typer.testing import CliRunner

from frpdeck.cli import app
from frpdeck.services.runtime import CommandResult
from frpdeck.services.uninstall import analyze_uninstall_root_requirements, uninstall_instance
from frpdeck.storage.dump import dump_yaml_model
from tests.support import build_client_node


RUNNER = CliRunner()


def _write_instance(
    instance_dir: Path,
    *,
    client_log_to: str = "runtime/logs/frpc.log",
    frpdeck_log_path: str = "state/logs/frpdeck.log",
) -> None:
    dump_yaml_model(
        build_client_node(
            instance_name="demo-client",
            service_name="demo-client-frpc",
            overrides={
                "paths": {
                    "install_dir": "runtime/bin",
                    "config_root": "runtime/config",
                    "systemd_unit_dir": "systemd",
                },
                "frpdeck_logging": {"file_path": frpdeck_log_path},
                "client": {"log": {"to": client_log_to}},
            },
        ),
        instance_dir / "node.yaml",
    )
    (instance_dir / "proxies.yaml").write_text("proxies: []\n", encoding="utf-8")
    (instance_dir / "secrets").mkdir(parents=True, exist_ok=True)
    (instance_dir / "secrets" / "token.txt").write_text("secret\n", encoding="utf-8")
    (instance_dir / "runtime" / "bin").mkdir(parents=True, exist_ok=True)
    (instance_dir / "runtime" / "bin" / "frpc").write_text("binary\n", encoding="utf-8")
    (instance_dir / "runtime" / "config").mkdir(parents=True, exist_ok=True)
    (instance_dir / "runtime" / "config" / "frpc.toml").write_text("bindPort = 7000\n", encoding="utf-8")
    (instance_dir / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    (instance_dir / "state" / "logs").mkdir(parents=True, exist_ok=True)
    (instance_dir / "rendered").mkdir(parents=True, exist_ok=True)
    (instance_dir / "state").mkdir(parents=True, exist_ok=True)
    (instance_dir / "backups").mkdir(parents=True, exist_ok=True)
    (instance_dir / "systemd").mkdir(parents=True, exist_ok=True)
    (instance_dir / "systemd" / "demo-client-frpc.service").write_text("[Unit]\nDescription=test\n", encoding="utf-8")


def test_uninstall_keeps_source_config_by_default(monkeypatch, tmp_path: Path) -> None:
    _write_instance(tmp_path)

    monkeypatch.setattr("frpdeck.services.uninstall.command_exists", lambda command: False)

    result = RUNNER.invoke(app, ["uninstall", "--instance", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert not (tmp_path / "runtime").exists()
    assert not (tmp_path / "rendered").exists()
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "backups").exists()
    assert (tmp_path / "node.yaml").exists()
    assert (tmp_path / "proxies.yaml").exists()
    assert (tmp_path / "secrets").exists()
    assert "System installation artifacts have been removed." in result.stdout
    assert f"Instance configuration is still present in {tmp_path.resolve()}." in result.stdout


def test_uninstall_with_purge_removes_instance_directory(monkeypatch, tmp_path: Path) -> None:
    _write_instance(tmp_path)

    monkeypatch.setattr("frpdeck.services.uninstall.command_exists", lambda command: False)

    result = RUNNER.invoke(app, ["uninstall", "--instance", str(tmp_path), "--purge"])

    assert result.exit_code == 0, result.stdout
    assert not tmp_path.exists()
    assert f"Purged instance directory: {tmp_path.resolve()}" in result.stdout


def test_uninstall_rejects_dangerous_paths(monkeypatch, tmp_path: Path) -> None:
    _write_instance(tmp_path, client_log_to="/frpc.log")

    monkeypatch.setattr("frpdeck.services.uninstall.command_exists", lambda command: False)

    result = RUNNER.invoke(app, ["uninstall", "--instance", str(tmp_path)])

    assert result.exit_code == 1
    assert "refusing to delete dangerous path: /" in result.stdout


def test_uninstall_resets_failed_service_state_best_effort(monkeypatch, tmp_path: Path) -> None:
    _write_instance(tmp_path)
    calls: list[str] = []

    def _result(name: str, returncode: int = 0, *, stdout: str = "", stderr: str = "") -> CommandResult:
        return CommandResult(
            args=["systemctl", name, "demo-client-frpc.service"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    monkeypatch.setattr("frpdeck.services.uninstall.command_exists", lambda command: True)
    monkeypatch.setattr(
        "frpdeck.services.uninstall.stop_service",
        lambda service_name, check=False: calls.append("stop") or _result("stop"),
    )
    monkeypatch.setattr(
        "frpdeck.services.uninstall.disable_service",
        lambda service_name, check=False: calls.append("disable") or _result("disable"),
    )
    monkeypatch.setattr(
        "frpdeck.services.uninstall.remove_unit_file",
        lambda unit_path: calls.append("remove_unit"),
    )
    monkeypatch.setattr(
        "frpdeck.services.uninstall.daemon_reload",
        lambda: calls.append("daemon_reload"),
    )
    monkeypatch.setattr(
        "frpdeck.services.uninstall.reset_failed_service",
        lambda service_name, check=False: (
            calls.append("reset_failed") or _result("reset-failed", returncode=1, stderr="failed state already cleared")
        ),
    )

    report = uninstall_instance(tmp_path)

    assert calls.index("daemon_reload") < calls.index("reset_failed")
    assert any("could not clear failed service state cleanly" in warning for warning in report.warnings)
    assert any("failed state already cleared" in warning for warning in report.warnings)


def test_analyze_uninstall_root_requirements_allows_local_user_writable_paths(monkeypatch, tmp_path: Path) -> None:
    _write_instance(tmp_path)

    monkeypatch.setattr("frpdeck.services.uninstall.command_exists", lambda command: False)

    reasons = analyze_uninstall_root_requirements(tmp_path)

    assert reasons == []


def test_analyze_uninstall_root_requirements_reports_non_writable_purge_target(monkeypatch, tmp_path: Path) -> None:
    _write_instance(tmp_path)

    monkeypatch.setattr("frpdeck.services.uninstall.command_exists", lambda command: False)
    monkeypatch.setattr(
        "frpdeck.services.uninstall.can_delete_path", lambda path: False if path == tmp_path.resolve() else True
    )

    reasons = analyze_uninstall_root_requirements(tmp_path, purge=True)

    assert any("instance directory is not removable by current user" in reason for reason in reasons)
