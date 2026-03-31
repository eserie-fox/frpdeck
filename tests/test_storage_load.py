from pathlib import Path

from frpdeck.storage.load import load_node_config, load_proxy_file


def test_load_node_config_merges_role_defaults_from_package(tmp_path: Path) -> None:
    (tmp_path / "node.yaml").write_text(
        "\n".join(
            [
                "instance_name: demo-client",
                "role: client",
                "service:",
                "  service_name: demo-frpc",
                "client:",
                "  server_addr: example.com",
                "  auth:",
                "    token: secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    node = load_node_config(tmp_path)

    assert node.paths.install_dir == Path("runtime/bin")
    assert node.binary.arch == "amd64"
    assert node.service.user == "root"
    assert node.frpdeck_logging.file_path == Path("state/logs/frpdeck.log")
    assert node.client.server_port == 7000
    assert node.client.log.max_days == 7


def test_load_proxy_file_defaults_missing_and_empty_documents(tmp_path: Path) -> None:
    missing = load_proxy_file(tmp_path)
    assert missing.proxies == []

    (tmp_path / "proxies.yaml").write_text("{}\n", encoding="utf-8")
    empty = load_proxy_file(tmp_path)
    assert empty.proxies == []
