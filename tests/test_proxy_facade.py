from pathlib import Path
import json
import logging

from frpdeck.domain.proxy import ProxyFile, TcpProxyConfig
from frpdeck.facade.proxy_facade import ProxyFacade
from frpdeck.storage.dump import dump_yaml_model
from tests.support import build_client_node, build_server_node


def _write_client_instance(
    instance_dir: Path,
    proxies: list[object] | None = None,
    *,
    node_overrides: dict[str, object] | None = None,
) -> None:
    dump_yaml_model(
        build_client_node(overrides=node_overrides),
        instance_dir / "node.yaml",
    )
    dump_yaml_model(ProxyFile(proxies=list(proxies or [])), instance_dir / "proxies.yaml")


def _write_server_instance(instance_dir: Path) -> None:
    dump_yaml_model(
        build_server_node(),
        instance_dir / "node.yaml",
    )


def test_list_proxies_returns_schema_and_jsonable_data(tmp_path: Path) -> None:
    _write_client_instance(tmp_path, [TcpProxyConfig(name="ssh", local_port=22, remote_port=6000)])

    result = ProxyFacade().list_proxies(tmp_path)

    assert result.ok is True
    assert result.schema_version == "frpdeck.proxy.v1"
    assert result.data["count"] == 1
    assert result.data["proxies"][0]["name"] == "ssh"
    json.dumps(result.model_dump(mode="json"))


def test_get_proxy_returns_proxy_not_found_error_code(tmp_path: Path) -> None:
    _write_client_instance(tmp_path)

    result = ProxyFacade().get_proxy(tmp_path, "missing")

    assert result.ok is False
    assert result.error_code == "proxy_not_found"


def test_add_and_update_map_expected_error_codes(tmp_path: Path) -> None:
    facade = ProxyFacade()
    _write_client_instance(tmp_path, [TcpProxyConfig(name="ssh", local_port=22, remote_port=6000)])

    duplicate = facade.add_proxy(tmp_path, TcpProxyConfig(name="ssh", local_port=23, remote_port=6001))
    invalid_update = facade.update_proxy(tmp_path, "ssh", {"remote_port": 70000})

    assert duplicate.ok is False
    assert duplicate.error_code == "proxy_already_exists"
    assert invalid_update.ok is False
    assert invalid_update.error_code == "proxy_conflict"


def test_preview_returns_uniform_data_and_apply_rejects_server_role(tmp_path: Path) -> None:
    _write_client_instance(tmp_path, [TcpProxyConfig(name="ssh", local_port=22, remote_port=6000)])
    facade = ProxyFacade()

    preview = facade.preview_proxy_changes(tmp_path)

    assert preview.ok is True
    assert preview.operation == "preview_proxy_changes"
    assert preview.data["enabled_proxies"] == ["ssh"]

    server_dir = tmp_path / "server"
    server_dir.mkdir()
    _write_server_instance(server_dir)

    apply_result = facade.apply_proxy_changes(server_dir)

    assert apply_result.ok is False
    assert apply_result.error_code == "unsupported_role"


def test_facade_applies_instance_logging_for_bound_calls(tmp_path: Path) -> None:
    _write_client_instance(
        tmp_path,
        [],
        node_overrides={
            "frpdeck_logging": {
                "level": "INFO",
                "stream": "none",
                "file_path": "state/logs/frpdeck.log",
            }
        },
    )

    class LoggingManager:
        def list_proxies(self, instance_dir: Path) -> list[object]:
            logging.getLogger("frpdeck.facade-test").info("facade logging active")
            return []

    result = ProxyFacade(manager=LoggingManager()).list_proxies(tmp_path)

    assert result.ok is True
    assert (tmp_path / "state" / "logs" / "frpdeck.log").is_symlink()


def test_facade_returns_config_load_failed_when_instance_logging_init_fails(tmp_path: Path) -> None:
    result = ProxyFacade().list_proxies(tmp_path)

    assert result.ok is False
    assert result.error_code == "config_load_failed"
