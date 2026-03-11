"""Structured proxy management models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from frpdeck.domain.proxy import ProxyConfig


class ProxyTransportPatch(BaseModel):
    """Partial transport update payload."""

    model_config = ConfigDict(extra="forbid")

    use_encryption: bool | None = None
    use_compression: bool | None = None
    bandwidth_limit: str | None = None
    bandwidth_limit_mode: str | None = None


class ProxyUpdatePatch(BaseModel):
    """Partial proxy update payload."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    enabled: bool | None = None
    description: str | None = None
    local_ip: str | None = None
    local_port: int | None = Field(default=None, ge=1, le=65535)
    annotations: dict[str, str] | None = None
    metadatas: dict[str, str] | None = None
    transport: ProxyTransportPatch | None = None
    remote_port: int | None = Field(default=None, ge=1, le=65535)
    custom_domains: list[str] | None = None
    subdomain: str | None = None


class ProxyMutationResult(BaseModel):
    """Result of a structured proxy mutation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    operation: str
    changed: bool
    apply_required: bool = True
    proxy: ProxyConfig | None = None
    removed_name: str | None = None
    message: str
    warnings: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    """Structured validation outcome for a proxy set."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PreviewReport(BaseModel):
    """Preview result for pending proxy changes."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    enabled_proxies: list[str] = Field(default_factory=list)
    disabled_proxies: list[str] = Field(default_factory=list)
    rendered_proxy_files: list[str] = Field(default_factory=list)


class ApplyReport(BaseModel):
    """Apply result for proxy rendering and reload."""

    ok: bool
    step: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rendered_proxy_files: list[str] = Field(default_factory=list)
    reload_requested: bool = True
    reloaded: bool = False
    reload_output: str | None = None