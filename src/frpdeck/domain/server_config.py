"""Server-side FRP config models."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from frpdeck.domain.client_config import AuthConfig, FrpLogConfig


class ServerCommonConfig(BaseModel):
    """Structured server configuration."""

    model_config = ConfigDict(extra="forbid")

    bind_addr: str
    bind_port: int = Field(ge=1, le=65535)
    kcp_bind_port: int | None = Field(ge=1, le=65535)
    quic_bind_port: int | None = Field(ge=1, le=65535)
    vhost_http_port: int | None = Field(ge=1, le=65535)
    vhost_https_port: int | None = Field(ge=1, le=65535)
    subdomain_host: str | None = None
    log: FrpLogConfig
    auth: AuthConfig

    @field_validator("subdomain_host")
    @classmethod
    def _validate_subdomain_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("server.subdomain_host must not be empty")
        return normalized
