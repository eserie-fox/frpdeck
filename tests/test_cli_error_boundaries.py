import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from frpdeck.cli import app
from frpdeck.domain.errors import DownloadError, ReleaseNotFoundError
from frpdeck.storage.dump import dump_yaml_model
from tests.support import build_client_node

RUNNER = CliRunner()


def _assert_no_traceback(result) -> None:
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("broken_file", ["node.yaml", "proxies.yaml"])
def test_validate_reports_broken_yaml_on_stderr_without_traceback(tmp_path: Path, broken_file: str) -> None:
    dump_yaml_model(build_client_node(), tmp_path / "node.yaml")
    (tmp_path / "proxies.yaml").write_text("proxies: []\n", encoding="utf-8")
    (tmp_path / broken_file).write_text("broken: [\n", encoding="utf-8")

    result = RUNNER.invoke(app, ["validate", "--instance", str(tmp_path)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr
    _assert_no_traceback(result)


def test_check_update_reports_broken_node_config_on_stderr(tmp_path: Path) -> None:
    (tmp_path / "node.yaml").write_text("role: [\n", encoding="utf-8")

    result = RUNNER.invoke(app, ["check-update", "--instance", str(tmp_path)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr
    _assert_no_traceback(result)


@pytest.mark.parametrize(
    "failure",
    [
        DownloadError("GitHub release lookup unavailable"),
        ReleaseNotFoundError("managed FRP release asset is missing"),
    ],
)
def test_check_update_reports_release_failures_without_traceback(
    monkeypatch, tmp_path: Path, failure: Exception
) -> None:
    dump_yaml_model(build_client_node(), tmp_path / "node.yaml")
    monkeypatch.setattr(
        "frpdeck.commands.check_update.get_release",
        lambda binary: (_ for _ in ()).throw(failure),
    )

    result = RUNNER.invoke(app, ["check-update", "--instance", str(tmp_path)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr
    _assert_no_traceback(result)


def test_status_human_mode_keeps_partial_status_and_writes_errors_to_stderr(tmp_path: Path) -> None:
    (tmp_path / "node.yaml").write_text("role: [\n", encoding="utf-8")

    result = RUNNER.invoke(app, ["status", "--instance", str(tmp_path)])

    assert result.exit_code == 1
    assert result.stdout
    assert result.stderr
    _assert_no_traceback(result)


def test_status_json_mode_returns_one_parseable_error_envelope(tmp_path: Path) -> None:
    (tmp_path / "node.yaml").write_text("role: [\n", encoding="utf-8")

    result = RUNNER.invoke(app, ["status", "--instance", str(tmp_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "status"
    assert payload["errors"]
    assert payload["data"]["config_summary"]["node_config_loaded"] is False
    assert result.stderr == ""
    _assert_no_traceback(result)


def test_proxy_json_error_keeps_stdout_clean_and_parseable(tmp_path: Path) -> None:
    (tmp_path / "node.yaml").write_text("role: [\n", encoding="utf-8")

    result = RUNNER.invoke(app, ["proxy", "list", "--instance", str(tmp_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "proxy list"
    assert payload["errors"]
    assert result.stderr == ""
    _assert_no_traceback(result)
