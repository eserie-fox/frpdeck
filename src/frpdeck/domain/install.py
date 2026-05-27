"""Binary installation configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from frpdeck.domain.enums import InstallChannel
from frpdeck.domain.versioning import normalize_version


class BinaryConfig(BaseModel):
    """Binary acquisition settings."""

    model_config = ConfigDict(extra="forbid")

    arch: str
    os: str
    channel: InstallChannel
    version: str | None = None
    local_archive: Path | None = None
    install_strategy: str | None

    @field_validator("local_archive", mode="before")
    @classmethod
    def _coerce_archive(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        return Path(value)

    @field_validator("version", mode="before")
    @classmethod
    def _normalize_version(cls, value: str | None) -> str | None:
        return normalize_version(value)
