"""Proxy models and discriminated union types."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from frpdeck.domain.enums import BandwidthLimitMode, ProxyType


def validate_http_proxy_routes(
    custom_domains: list[str],
    subdomain: str | None,
    *,
    scope: str,
) -> tuple[list[str], str | None]:
    """Normalize and validate HTTP/HTTPS route selectors."""

    normalized_domains: list[str] = []
    for domain in custom_domains:
        normalized = domain.strip()
        if not normalized:
            raise ValueError(f"{scope}.custom_domains must not contain empty values")
        normalized_domains.append(normalized)

    normalized_subdomain = None
    if subdomain is not None:
        normalized_subdomain = subdomain.strip()
        if not normalized_subdomain:
            raise ValueError(f"{scope}.subdomain must not be empty")

    if not normalized_domains and normalized_subdomain is None:
        raise ValueError(f"{scope} requires custom_domains or subdomain")

    return normalized_domains, normalized_subdomain


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

    @model_validator(mode="after")
    def _validate_routes(self) -> "HttpProxyConfig":
        self.custom_domains, self.subdomain = validate_http_proxy_routes(
            self.custom_domains,
            self.subdomain,
            scope=f"proxy {self.name}",
        )
        return self


class HttpsProxyConfig(ProxyBase):
    type: Literal[ProxyType.HTTPS] = ProxyType.HTTPS
    custom_domains: list[str] = Field(default_factory=list)
    subdomain: str | None = None

    @model_validator(mode="after")
    def _validate_routes(self) -> "HttpsProxyConfig":
        self.custom_domains, self.subdomain = validate_http_proxy_routes(
            self.custom_domains,
            self.subdomain,
            scope=f"proxy {self.name}",
        )
        return self


ProxyConfig = Annotated[
    TcpProxyConfig | UdpProxyConfig | HttpProxyConfig | HttpsProxyConfig,
    Field(discriminator="type"),
]

PROXY_ADAPTER = TypeAdapter(ProxyConfig)


class ProxyFile(BaseModel):
    """Top-level proxy document."""

    model_config = ConfigDict(extra="forbid")

    proxies: list[ProxyConfig] = Field(default_factory=list)
