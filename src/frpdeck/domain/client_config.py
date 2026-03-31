"""Client-side FRP config models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from frpdeck.domain.enums import FrpLogLevel, TransportProtocol


class FrpLogConfig(BaseModel):
    """Shared FRP log settings."""

    model_config = ConfigDict(extra="forbid")

    to: Path | None
    level: FrpLogLevel
    max_days: int
    disable_print_color: bool

    @field_validator("to", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        return Path(value)


class AuthConfig(BaseModel):
    """Authentication settings."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["token"]
    token: str | None = None
    token_file: Path | None = None

    @field_validator("token_file", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        return Path(value)

    @model_validator(mode="after")
    def _validate_token_sources(self) -> "AuthConfig":
        if self.token and self.token_file:
            raise ValueError("auth.token and auth.token_file are mutually exclusive")
        return self


class WebServerConfig(BaseModel):
    """Admin web server settings for frpc."""

    model_config = ConfigDict(extra="forbid")

    addr: str | None
    port: int | None


class ClientCommonConfig(BaseModel):
    """Structured client configuration."""

    model_config = ConfigDict(extra="forbid")

    user: str | None = None
    server_addr: str
    server_port: int = Field(ge=1, le=65535)
    transport_protocol: TransportProtocol
    web_server: WebServerConfig
    login_fail_exit: bool
    log: FrpLogConfig
    auth: AuthConfig
    includes_enabled: bool
