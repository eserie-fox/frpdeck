"""Server-side FRP config models."""

from pydantic import BaseModel, ConfigDict, Field

from frpdeck.domain.client_config import AuthConfig, FrpLogConfig


class ServerCommonConfig(BaseModel):
    """Structured server configuration."""

    model_config = ConfigDict(extra="forbid")

    bind_addr: str = "0.0.0.0"
    bind_port: int = Field(default=7000, ge=1, le=65535)
    kcp_bind_port: int | None = Field(default=None, ge=1, le=65535)
    quic_bind_port: int | None = Field(default=None, ge=1, le=65535)
    vhost_http_port: int | None = Field(default=80, ge=1, le=65535)
    vhost_https_port: int | None = Field(default=443, ge=1, le=65535)
    subdomain_host: str | None = None
    log: FrpLogConfig = Field(default_factory=FrpLogConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
