"""frpdeck application logging config models."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from frpdeck.domain.enums import FrpdeckLogLevel


LoggingStream = Literal["stdout", "stderr", "none"]

_LOG_LEVEL_TO_STDLIB: dict[FrpdeckLogLevel, int] = {
    FrpdeckLogLevel.CRITICAL: logging.CRITICAL,
    FrpdeckLogLevel.ERROR: logging.ERROR,
    FrpdeckLogLevel.WARNING: logging.WARNING,
    FrpdeckLogLevel.INFO: logging.INFO,
    FrpdeckLogLevel.DEBUG: logging.DEBUG,
    FrpdeckLogLevel.NOTSET: logging.NOTSET,
}


class FrpdeckLoggingConfig(BaseModel):
    """Instance-scoped logging config for frpdeck itself."""

    model_config = ConfigDict(extra="forbid")

    level: FrpdeckLogLevel
    format: str
    file_path: Path | None
    retention_days: int
    stream: LoggingStream

    @field_validator("file_path", mode="before")
    @classmethod
    def _coerce_file_path(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        return Path(value)

    @field_validator("retention_days")
    @classmethod
    def _validate_retention_days(cls, value: int) -> int:
        if value < 1:
            raise ValueError("frpdeck_logging.retention_days must be >= 1")
        return value

    def resolved_level(self) -> int:
        """Return the stdlib logging level integer."""

        return _LOG_LEVEL_TO_STDLIB[self.level]

    def resolved_log_path(self, instance_dir: Path) -> Path | None:
        """Resolve the configured log path against one instance directory."""

        if self.file_path is None:
            return None
        raw_path = self.file_path.expanduser()
        if raw_path.is_absolute():
            return raw_path.parent.resolve() / raw_path.name
        resolved_path = instance_dir / raw_path
        return resolved_path.parent.resolve() / resolved_path.name


__all__ = ["FrpdeckLoggingConfig", "LoggingStream"]
