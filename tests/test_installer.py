from pathlib import Path

import pytest

from frpdeck.domain.errors import ConfigValidationError
from frpdeck.services.installer import sync_rendered_to_runtime
from tests.support import build_client_node, build_server_node


def test_sync_rendered_to_runtime_creates_frp_log_parent_from_client_log_path(tmp_path: Path) -> None:
    node = build_client_node(overrides={"client": {"log": {"to": "custom-logs/frpc.log"}}})

    rendered_root = tmp_path / "rendered"
    (rendered_root / "frpc.toml").parent.mkdir(parents=True, exist_ok=True)
    (rendered_root / "frpc.toml").write_text("serverAddr = 'example.com'\n", encoding="utf-8")
    (rendered_root / "proxies.d" / "ssh.toml").parent.mkdir(parents=True, exist_ok=True)
    (rendered_root / "proxies.d" / "ssh.toml").write_text("[[proxies]]\n", encoding="utf-8")

    config_path = sync_rendered_to_runtime(tmp_path, node)

    assert config_path == (tmp_path / "runtime" / "config" / "frpc.toml")
    assert (tmp_path / "runtime" / "config" / "frpc.toml").exists()
    assert (tmp_path / "runtime" / "config" / "proxies.d" / "ssh.toml").exists()
    assert (tmp_path / "custom-logs").is_dir()


def test_sync_rendered_to_runtime_replaces_client_proxy_include_directory(tmp_path: Path) -> None:
    node = build_client_node()

    rendered_root = tmp_path / "rendered"
    rendered_root.mkdir(parents=True, exist_ok=True)
    (rendered_root / "frpc.toml").write_text("serverAddr = 'example.com'\n", encoding="utf-8")
    (rendered_root / "proxies.d").mkdir(parents=True, exist_ok=True)
    (rendered_root / "proxies.d" / "new.toml").write_text("[[proxies]]\n", encoding="utf-8")

    runtime_proxies = tmp_path / "runtime" / "config" / "proxies.d"
    runtime_proxies.mkdir(parents=True, exist_ok=True)
    (runtime_proxies / "old.toml").write_text("stale", encoding="utf-8")
    runtime_other = tmp_path / "runtime" / "state"
    runtime_other.mkdir(parents=True, exist_ok=True)
    (runtime_other / "keep.txt").write_text("keep", encoding="utf-8")

    sync_rendered_to_runtime(tmp_path, node)

    assert not (runtime_proxies / "old.toml").exists()
    assert (runtime_proxies / "new.toml").exists()
    assert (runtime_other / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_sync_rendered_to_runtime_requires_client_rendered_proxy_snapshot(tmp_path: Path) -> None:
    node = build_client_node()

    rendered_root = tmp_path / "rendered"
    rendered_root.mkdir(parents=True, exist_ok=True)
    (rendered_root / "frpc.toml").write_text("serverAddr = 'example.com'\n", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="rendered proxy include directory not found"):
        sync_rendered_to_runtime(tmp_path, node)


def test_sync_rendered_to_runtime_allows_server_without_proxies_directory(tmp_path: Path) -> None:
    node = build_server_node()

    rendered_root = tmp_path / "rendered"
    rendered_root.mkdir(parents=True, exist_ok=True)
    (rendered_root / "frps.toml").write_text("bindPort = 7000\n", encoding="utf-8")

    config_path = sync_rendered_to_runtime(tmp_path, node)

    assert config_path == (tmp_path / "runtime" / "config" / "frps.toml")
    assert config_path.exists()
    assert not (tmp_path / "runtime" / "config" / "proxies.d").exists()
