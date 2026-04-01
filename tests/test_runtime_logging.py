import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest

from frpdeck.domain.errors import ConfigLoadError
from frpdeck.logging import (
    DailySymlinkFileHandler,
    ResolvedLoggingConfig,
    apply_logging_config,
    configure_default_logging,
    instance_logging_context,
    load_instance_logging_config,
)
from frpdeck.storage.dump import dump_yaml_model
from tests.support import build_client_node


@contextmanager
def _restore_root_logger() -> object:
    root = logging.getLogger()
    level = root.level
    handlers = list(root.handlers)
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            if handler not in handlers:
                handler.close()
        root.setLevel(level)
        for handler in handlers:
            root.addHandler(handler)


def test_daily_symlink_handler_is_lazy_until_first_record(tmp_path: Path) -> None:
    current = datetime(2026, 3, 31, 12, 0, 0)

    def now() -> datetime:
        return current

    handler = DailySymlinkFileHandler(tmp_path / "frpdeck.log", now_func=now)

    assert not (tmp_path / "frpdeck.log").exists()
    assert not any(tmp_path.iterdir())

    record = logging.makeLogRecord(
        {
            "name": "frpdeck.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "hello world",
        }
    )
    handler.emit(record)
    handler.close()

    symlink = tmp_path / "frpdeck.log"
    daily_file = tmp_path / "frpdeck-2026-03-31.log"
    assert symlink.is_symlink()
    assert symlink.resolve() == daily_file.resolve()
    assert "hello world" in daily_file.read_text(encoding="utf-8")


def test_daily_symlink_handler_prunes_old_files_by_retention(tmp_path: Path) -> None:
    current = datetime(2026, 3, 31, 12, 0, 0)

    def now() -> datetime:
        return current

    old_file = tmp_path / "frpdeck-2026-03-28.log"
    keep_file = tmp_path / "frpdeck-2026-03-30.log"
    old_file.write_text("old", encoding="utf-8")
    keep_file.write_text("keep", encoding="utf-8")

    handler = DailySymlinkFileHandler(
        tmp_path / "frpdeck.log",
        retention_days=2,
        now_func=now,
    )
    handler.emit(
        logging.makeLogRecord(
            {
                "name": "frpdeck.test",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "msg": "rotate",
            }
        )
    )
    handler.close()

    assert not old_file.exists()
    assert keep_file.exists()
    assert (tmp_path / "frpdeck-2026-03-31.log").exists()


def test_configure_default_logging_uses_stderr_by_default(capsys) -> None:
    with _restore_root_logger():
        configure_default_logging()
        logging.getLogger("frpdeck.test").warning("default logging active")

    captured = capsys.readouterr()
    assert "default logging active" in captured.err


def test_load_instance_logging_config_returns_resolved_config_without_mutating_root_logger(tmp_path: Path) -> None:
    dump_yaml_model(
        build_client_node(
            overrides={
                "frpdeck_logging": {
                    "level": "DEBUG",
                    "stream": "none",
                    "file_path": "state/logs/frpdeck.log",
                }
            }
        ),
        tmp_path / "node.yaml",
    )
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)

    resolved_node, config = load_instance_logging_config(tmp_path)

    assert resolved_node.instance_name == "client-demo"
    assert config.level == logging.DEBUG
    assert config.stream == "none"
    assert config.file_path == (tmp_path / "state" / "logs" / "frpdeck.log").resolve()
    assert root.level == original_level
    assert list(root.handlers) == original_handlers


def test_apply_logging_config_uses_supplied_runtime_config(tmp_path: Path) -> None:
    config = ResolvedLoggingConfig(
        level=logging.INFO,
        format="%(message)s",
        file_path=tmp_path / "frpdeck.log",
        retention_days=7,
        stream="none",
    )

    with _restore_root_logger():
        apply_logging_config(config, close_existing=True)
        logging.getLogger("frpdeck.test").info("applied from runtime config")

    symlink = tmp_path / "frpdeck.log"
    assert symlink.is_symlink()
    assert "applied from runtime config" in symlink.resolve().read_text(encoding="utf-8")


def test_instance_logging_context_uses_instance_file_and_restores_previous_handlers(tmp_path: Path, capsys) -> None:
    dump_yaml_model(
        build_client_node(
            overrides={
                "frpdeck_logging": {
                    "level": "INFO",
                    "stream": "none",
                    "file_path": "state/logs/frpdeck.log",
                }
            }
        ),
        tmp_path / "node.yaml",
    )

    with _restore_root_logger():
        configure_default_logging()
        with instance_logging_context(tmp_path):
            logging.getLogger("frpdeck.test").info("instance logging active")
        logging.getLogger("frpdeck.test").warning("restored stderr logging")

    captured = capsys.readouterr()
    assert "restored stderr logging" in captured.err
    symlink = tmp_path / "state" / "logs" / "frpdeck.log"
    assert symlink.is_symlink()
    assert "instance logging active" in symlink.resolve().read_text(encoding="utf-8")


def test_instance_logging_context_stream_override_none_suppresses_console_and_keeps_file_logging(tmp_path: Path, capsys) -> None:
    dump_yaml_model(
        build_client_node(
            overrides={
                "frpdeck_logging": {
                    "level": "INFO",
                    "stream": "stdout",
                    "file_path": "state/logs/frpdeck.log",
                }
            }
        ),
        tmp_path / "node.yaml",
    )

    with _restore_root_logger():
        with instance_logging_context(tmp_path, stream_override="none"):
            logging.getLogger("frpdeck.test").info("no console output")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    symlink = tmp_path / "state" / "logs" / "frpdeck.log"
    assert symlink.is_symlink()
    assert "no console output" in symlink.resolve().read_text(encoding="utf-8")


def test_instance_logging_context_without_override_honors_configured_stream(tmp_path: Path, capsys) -> None:
    dump_yaml_model(
        build_client_node(
            overrides={
                "frpdeck_logging": {
                    "level": "INFO",
                    "stream": "stdout",
                    "file_path": None,
                }
            }
        ),
        tmp_path / "node.yaml",
    )

    with _restore_root_logger():
        with instance_logging_context(tmp_path):
            logging.getLogger("frpdeck.test").info("stdout logging active")

    captured = capsys.readouterr()
    assert "stdout logging active" in captured.out
    assert captured.err == ""


def test_instance_logging_context_fails_fast_for_missing_node_config(tmp_path: Path) -> None:
    with _restore_root_logger():
        configure_default_logging()
        with pytest.raises(ConfigLoadError, match="config file not found"):
            with instance_logging_context(tmp_path):
                pass


def test_instance_logging_context_fails_fast_for_invalid_logging_config(tmp_path: Path) -> None:
    (tmp_path / "node.yaml").write_text(
        "\n".join(
            [
                "instance_name: demo-client",
                "role: client",
                "service:",
                "  service_name: demo-frpc",
                "frpdeck_logging:",
                "  level: WARN",
                "client:",
                "  server_addr: example.com",
                "  auth:",
                "    token: secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with _restore_root_logger():
        configure_default_logging()
        with pytest.raises(ConfigLoadError, match="invalid node config"):
            with instance_logging_context(tmp_path):
                pass
