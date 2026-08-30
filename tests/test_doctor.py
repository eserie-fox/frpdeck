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

    result = RUNNER.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert f"[OK] node.yaml: expected {tmp_path / 'node.yaml'}" in result.stdout
    assert "[OK] instance configuration:" in result.stdout


def test_doctor_uses_explicit_instance(monkeypatch, tmp_path: Path) -> None:
    _make_system_checks_pass(monkeypatch)
    instance = tmp_path / "instance"
    _write_valid_instance(instance)

    result = RUNNER.invoke(app, ["doctor", "--instance", str(instance)])

    assert result.exit_code == 0, result.output
    assert str(instance / "node.yaml") in result.stdout


def test_doctor_system_only_skips_instance_checks(monkeypatch, tmp_path: Path) -> None:
    _make_system_checks_pass(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = RUNNER.invoke(app, ["doctor", "--system-only"])

    assert result.exit_code == 0, result.output
    assert "[OK] platform:" in result.stdout
    assert "node.yaml" not in result.output
    assert "instance configuration" not in result.output


def test_doctor_rejects_instance_with_system_only(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, ["doctor", "--instance", str(tmp_path), "--system-only"])

    assert result.exit_code == 2
    assert "cannot be combined with" in result.stderr
    assert "--system-only" in result.stderr
    assert "Traceback" not in result.output


def test_doctor_reports_missing_node_yaml(monkeypatch, tmp_path: Path) -> None:
    _make_system_checks_pass(monkeypatch)
    (tmp_path / "state").mkdir()

    result = RUNNER.invoke(app, ["doctor", "--instance", str(tmp_path)])

    assert result.exit_code == 1
    assert "[FAIL] node.yaml:" in result.stderr
    assert "ERROR: doctor found issues" in result.stderr
    assert "Traceback" not in result.output


def test_doctor_reports_broken_config_as_failed_check_and_continues_system_checks(monkeypatch, tmp_path: Path) -> None:
    _make_system_checks_pass(monkeypatch)
    (tmp_path / "node.yaml").write_text("role: [\n", encoding="utf-8")
    (tmp_path / "state").mkdir()

    result = RUNNER.invoke(app, ["doctor", "--instance", str(tmp_path)])

    assert result.exit_code == 1
    assert "[OK] platform:" in result.stdout
    assert "[OK] node.yaml:" in result.stdout
    assert "[FAIL] instance configuration: invalid YAML" in result.stderr
    assert "Traceback" not in result.output


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
