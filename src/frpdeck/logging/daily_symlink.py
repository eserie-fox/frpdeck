"""Daily rotating file handler with symlink updates."""

from __future__ import annotations

import logging
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator

from frpdeck.domain.frpdeck_logging import LoggingStream
from frpdeck.domain.state import NodeBase


DEFAULT_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
DEFAULT_LOG_LEVEL = logging.INFO
DEFAULT_RETENTION_DAYS = 7


class DailySymlinkFileHandler(logging.Handler):
    """Write logs to daily files and keep a stable symlink to the latest file.

    The provided path is expected to be the stable symlink name, not a resolved
    daily log target from a previous rotation.
    """

    def __init__(
        self,
        symlink_path: str | Path,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        encoding: str = "utf-8",
        now_func: Callable[[], datetime] = datetime.now,
    ) -> None:
        super().__init__()
        path = Path(symlink_path).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()

        self.symlink_path = path
        self.log_dir = path.parent
        self.stem = path.stem
        self.retention_days = max(1, retention_days)
        self.encoding = encoding
        self._now = now_func
        self._lock = threading.RLock()
        self._current_date: str | None = None
        self._file_handler: logging.FileHandler | None = None

    @property
    def current_log_path(self) -> Path | None:
        if self._file_handler is None:
            return None
        return Path(self._file_handler.baseFilename)

    def setFormatter(self, fmt: logging.Formatter) -> None:  # noqa: D401,N802
        super().setFormatter(fmt)
        if self._file_handler is not None:
            self._file_handler.setFormatter(fmt)

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        with self._lock:
            self._rotate_if_needed()
            if self._file_handler is not None:
                self._file_handler.emit(record)

    def flush(self) -> None:  # noqa: D401
        with self._lock:
            if self._file_handler is not None:
                self._file_handler.flush()

    def close(self) -> None:  # noqa: D401
        with self._lock:
            if self._file_handler is not None:
                self._file_handler.close()
                self._file_handler = None
        super().close()

    def _rotate_if_needed(self) -> None:
        today = self._now().strftime("%Y-%m-%d")
        if self._current_date == today and self._file_handler is not None:
            return

        if self._file_handler is not None:
            self._file_handler.close()

        self.log_dir.mkdir(parents=True, exist_ok=True)
        daily_file = self.log_dir / f"{self.stem}-{today}.log"
        self._file_handler = logging.FileHandler(daily_file, encoding=self.encoding)
        if self.formatter is not None:
            self._file_handler.setFormatter(self.formatter)

        self._current_date = today
        _cleanup_old_logs(
            self.log_dir,
            stem=self.stem,
            retention_days=self.retention_days,
            keep_file=daily_file,
            now_func=self._now,
        )
        _update_symlink(self.symlink_path, daily_file)


@dataclass(slots=True)
class _RootLoggerState:
    level: int
    handlers: list[logging.Handler]


@dataclass(slots=True, frozen=True)
class ResolvedLoggingConfig:
    """Apply-ready runtime logging configuration."""

    level: int
    format: str
    file_path: Path | None
    retention_days: int
    stream: LoggingStream


def configure_default_logging(
    *,
    stream_name: LoggingStream = "stderr",
    level: int = DEFAULT_LOG_LEVEL,
    fmt: str = DEFAULT_LOG_FORMAT,
) -> None:
    """Configure simple no-instance logging."""

    apply_logging_config(
        ResolvedLoggingConfig(
            level=level,
            format=fmt,
            file_path=None,
            retention_days=DEFAULT_RETENTION_DAYS,
            stream=stream_name,
        ),
        close_existing=True,
    )


def load_instance_logging_config(
    instance_dir: Path,
    *,
    node: NodeBase | None = None,
    stream_override: LoggingStream | None = None,
) -> tuple[NodeBase, ResolvedLoggingConfig]:
    """Load one instance's frpdeck logging config without mutating the logger."""

    from frpdeck.storage.load import load_node_config

    resolved_instance_dir = instance_dir.resolve()
    resolved_node = node or load_node_config(resolved_instance_dir)
    config = resolved_node.frpdeck_logging
    resolved_config = ResolvedLoggingConfig(
        level=config.resolved_level(),
        format=config.format,
        file_path=config.resolved_log_path(resolved_instance_dir),
        retention_days=config.retention_days,
        stream=config.stream,
    )
    if stream_override is not None:
        resolved_config = replace(resolved_config, stream=stream_override)
    return resolved_node, resolved_config


def configure_instance_logging(
    instance_dir: Path,
    node: NodeBase,
    *,
    stream_override: LoggingStream | None = None,
) -> Path | None:
    """Configure logging from one loaded instance config."""

    _, config = load_instance_logging_config(instance_dir, node=node, stream_override=stream_override)
    return apply_logging_config(config, close_existing=True)


@contextmanager
def instance_logging_context(
    instance_dir: Path,
    *,
    node: NodeBase | None = None,
    stream_override: LoggingStream | None = None,
) -> Iterator[NodeBase]:
    """Temporarily apply one instance's frpdeck logging configuration."""

    resolved_node, config = load_instance_logging_config(instance_dir, node=node, stream_override=stream_override)
    snapshot = _capture_root_logger()
    try:
        apply_logging_config(config, close_existing=False)
        yield resolved_node
    finally:
        _restore_root_logger(snapshot)


def apply_logging_config(
    config: ResolvedLoggingConfig,
    *,
    close_existing: bool,
) -> Path | None:
    """Replace root logger handlers with one already-resolved configuration."""

    formatter = logging.Formatter(config.format)
    handlers: list[logging.Handler] = []
    log_path = config.file_path

    if log_path is not None:
        file_handler = DailySymlinkFileHandler(
            log_path,
            retention_days=config.retention_days,
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    if config.stream == "stdout":
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)
    elif config.stream == "stderr":
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)
    if not handlers:
        handlers.append(logging.NullHandler())

    _replace_root_logger_handlers(level=config.level, handlers=handlers, close_existing=close_existing)

    return log_path


def _capture_root_logger() -> _RootLoggerState:
    root_logger = logging.getLogger()
    return _RootLoggerState(level=root_logger.level, handlers=list(root_logger.handlers))


def _restore_root_logger(state: _RootLoggerState) -> None:
    _replace_root_logger_handlers(
        level=state.level,
        handlers=state.handlers,
        close_existing=True,
        preserved_handlers=state.handlers,
    )


def _replace_root_logger_handlers(
    *,
    level: int,
    handlers: list[logging.Handler],
    close_existing: bool,
    preserved_handlers: list[logging.Handler] | None = None,
) -> None:
    root_logger = logging.getLogger()
    preserved = set(preserved_handlers or [])
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        if close_existing and handler not in preserved:
            handler.close()
    root_logger.setLevel(level)
    for handler in handlers:
        root_logger.addHandler(handler)


def _cleanup_old_logs(
    log_dir: Path,
    *,
    stem: str,
    retention_days: int,
    keep_file: Path,
    now_func: Callable[[], datetime],
) -> None:
    cutoff = now_func().date() - timedelta(days=max(1, retention_days) - 1)

    for candidate in log_dir.glob(f"{stem}-*.log"):
        if candidate == keep_file:
            continue

        suffix = candidate.stem[len(stem) + 1 :]
        try:
            candidate_date = datetime.strptime(suffix, "%Y-%m-%d").date()
        except ValueError:
            continue

        if candidate_date < cutoff:
            candidate.unlink(missing_ok=True)


def _update_symlink(link_path: Path, current_file: Path) -> None:
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    link_path.symlink_to(current_file)


__all__ = [
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_RETENTION_DAYS",
    "DailySymlinkFileHandler",
    "ResolvedLoggingConfig",
    "apply_logging_config",
    "configure_default_logging",
    "configure_instance_logging",
    "instance_logging_context",
    "load_instance_logging_config",
]
