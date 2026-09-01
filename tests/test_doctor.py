from pathlib import Path

from typer.testing import CliRunner

from frpdeck.cli import app
from frpdeck.services.doctor import run_doctor
from frpdeck.storage.dump import dump_yaml_model
from tests.support import build_client_node

RUNNER = CliRunner()


def _make_system_checks_pass(monkeypatch) -> None:
    monkeypatch.setattr("frpdeck.services.doctor.command_exists", lambda command: True)
    monkeypatch.setattr("frpdeck.services.doctor._has_write_access", lambda path: True)


def _write_valid_instance(instance_dir: Path) -> None:
    dump_yaml_model(build_client_node(), instance_dir / "node.yaml")
    (instance_dir / "state").mkdir(parents=True, exist_ok=True)


def test_doctor_defaults_to_current_directory(monkeypatch, tmp_path: Path) -> None:
    _make_system_checks_pass(monkeypatch)
    _write_valid_instance(tmp_path)
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "frpdeck.commands.doctor.run_doctor",
        lambda instance_dir, node, *, config_error=None: (
            captured.update(
                instance_dir=instance_dir,
                node=node,
                config_error=config_error,
            )
            or []
        ),
    )

    result = RUNNER.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert captured["instance_dir"] == tmp_path.resolve()
    assert captured["node"].instance_name == "client-demo"
    assert captured["config_error"] is None


def test_doctor_uses_explicit_instance(monkeypatch, tmp_path: Path) -> None:
    _make_system_checks_pass(monkeypatch)
    instance = tmp_path / "instance"
    _write_valid_instance(instance)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "frpdeck.commands.doctor.run_doctor",
        lambda instance_dir, node, *, config_error=None: (
            captured.update(
                instance_dir=instance_dir,
                node=node,
                config_error=config_error,
            )
            or []
        ),
    )

    result = RUNNER.invoke(app, ["doctor", "--instance", str(instance)])

    assert result.exit_code == 0, result.output
    assert captured["instance_dir"] == instance.resolve()
    assert captured["node"].instance_name == "client-demo"


def test_doctor_system_only_skips_instance_checks(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "frpdeck.commands.doctor.run_doctor",
        lambda instance_dir, node, *, config_error=None: (
            captured.update(
                instance_dir=instance_dir,
                node=node,
                config_error=config_error,
            )
            or []
        ),
    )

    result = RUNNER.invoke(app, ["doctor", "--system-only"])

    assert result.exit_code == 0, result.output
    assert captured == {"instance_dir": None, "node": None, "config_error": None}


def test_doctor_rejects_instance_with_system_only(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr("frpdeck.commands.doctor.run_doctor", lambda *args, **kwargs: calls.append("doctor"))

    result = RUNNER.invoke(app, ["doctor", "--instance", str(tmp_path), "--system-only"])

    assert result.exit_code == 2
    assert calls == []


def test_doctor_reports_missing_node_yaml(monkeypatch, tmp_path: Path) -> None:
    _make_system_checks_pass(monkeypatch)
    (tmp_path / "state").mkdir()

    result = RUNNER.invoke(app, ["doctor", "--instance", str(tmp_path)])

    assert result.exit_code == 1
    checks = run_doctor(tmp_path, None)
    by_name = {check.name: check for check in checks}
    assert by_name["node.yaml"].ok is False


def test_doctor_reports_broken_config_as_failed_check_and_continues_system_checks(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "node.yaml").write_text("role: [\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "frpdeck.commands.doctor.run_doctor",
        lambda instance_dir, node, *, config_error=None: (
            captured.update(
                instance_dir=instance_dir,
                node=node,
                config_error=config_error,
            )
            or []
        ),
    )

    result = RUNNER.invoke(app, ["doctor", "--instance", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["instance_dir"] == tmp_path.resolve()
    assert captured["node"] is None
    assert "invalid YAML" in str(captured["config_error"])


def test_doctor_permission_checks_are_deterministic(monkeypatch, tmp_path: Path) -> None:
    node = build_client_node(
        overrides={
            "paths": {
                "install_dir": str(tmp_path / "managed-bin"),
                "systemd_unit_dir": str(tmp_path / "units"),
            }
        }
    )
    monkeypatch.setattr("frpdeck.services.doctor.command_exists", lambda command: True)
    monkeypatch.setattr(
        "frpdeck.services.doctor._has_write_access",
        lambda path: path.name != "units",
    )

    checks = run_doctor(tmp_path, node)
    by_name = {check.name: check for check in checks}

    assert by_name["install_dir write"].ok is True
    assert by_name["systemd_unit_dir write"].ok is False
