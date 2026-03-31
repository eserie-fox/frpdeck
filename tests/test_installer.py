from pathlib import Path

from frpdeck.services.installer import sync_rendered_to_runtime
from tests.support import build_client_node


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
