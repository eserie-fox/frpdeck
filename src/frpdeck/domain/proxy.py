"""Proxy models and discriminated union types."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from frpdeck.domain.enums import BandwidthLimitMode, ProxyType


class ProxyTransportConfig(BaseModel):
    """Transport tuning shared by all proxies."""

    model_config = ConfigDict(extra="forbid")

    use_encryption: bool = False
    use_compression: bool = False
    bandwidth_limit: str | None = None
    bandwidth_limit_mode: BandwidthLimitMode | None = None


class ProxyBase(BaseModel):
    """Common proxy fields."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    name: str
    type: ProxyType
    description: str | None = None
    local_ip: str = "127.0.0.1"
    local_port: int = Field(ge=1, le=65535)
    annotations: dict[str, str] = Field(default_factory=dict)
    metadatas: dict[str, str] = Field(default_factory=dict)
    transport: ProxyTransportConfig = Field(default_factory=ProxyTransportConfig)


class TcpProxyConfig(ProxyBase):
    type: Literal[ProxyType.TCP] = ProxyType.TCP
    remote_port: int = Field(ge=1, le=65535)


class UdpProxyConfig(ProxyBase):
    type: Literal[ProxyType.UDP] = ProxyType.UDP
    remote_port: int = Field(ge=1, le=65535)


class HttpProxyConfig(ProxyBase):
    type: Literal[ProxyType.HTTP] = ProxyType.HTTP
    custom_domains: list[str] = Field(default_factory=list)
    subdomain: str | None = None


class HttpsProxyConfig(ProxyBase):
    type: Literal[ProxyType.HTTPS] = ProxyType.HTTPS
    custom_domains: list[str] = Field(default_factory=list)
    subdomain: str | None = None


ProxyConfig = Annotated[
    TcpProxyConfig | UdpProxyConfig | HttpProxyConfig | HttpsProxyConfig,
    Field(discriminator="type"),
]

PROXY_ADAPTER = TypeAdapter(ProxyConfig)


class ProxyFile(BaseModel):
    """Top-level proxy document."""

    model_config = ConfigDict(extra="forbid")

    proxies: list[ProxyConfig] = Field(default_factory=list)
