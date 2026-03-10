from pathlib import Path

from typer.testing import CliRunner

from frpdeck.cli import app


RUNNER = CliRunner()


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

