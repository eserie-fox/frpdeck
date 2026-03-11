"""Structured read-only instance status models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConfigSummary(BaseModel):
    node_config_loaded: bool = False
    proxy_config_loaded: bool = False
    proxy_total: int = 0
    enabled_proxies: int = 0
    disabled_proxies: int = 0


class ProxyCounts(BaseModel):
    total: int = 0
    enabled: int = 0
    disabled: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)


class LastApplyStatus(BaseModel):
    applied_at: str | None = None
    service_name: str | None = None
    config_path: str | None = None


class RenderSummaryStatus(BaseModel):
    main_config_exists: bool = False
    rendered_proxy_files: list[str] = Field(default_factory=list)
    rendered_proxy_count: int = 0
    matches_enabled_proxy_count: bool | None = None


class ServiceRuntimeStatus(BaseModel):
    available: bool = False
    active: bool | None = None
    raw_output: str | None = None
    note: str | None = None


class ClientRuntimeStatus(BaseModel):
    available: bool = False
    raw_output: str | None = None
    note: str | None = None


class ProxyRuntimeStatus(BaseModel):
    name: str
    enabled: bool
    type: str
    description: str | None = None
    configured_target: str
    rendered_file: str | None = None
    included_in_current_render: bool = False
    runtime_present: bool | None = None
    notes: list[str] = Field(default_factory=list)


class InstanceStatus(BaseModel):
    schema_version: str = "frpdeck.status.v1"
    instance: str
    instance_name: str | None = None
    role: str | None = None
    service_name: str | None = None
    config_summary: ConfigSummary = Field(default_factory=ConfigSummary)
    proxy_counts: ProxyCounts = Field(default_factory=ProxyCounts)
    current_version: str | None = None
    last_apply: LastApplyStatus | None = None
    render_summary: RenderSummaryStatus = Field(default_factory=RenderSummaryStatus)
    service_status: ServiceRuntimeStatus = Field(default_factory=ServiceRuntimeStatus)
    client_runtime_status: ClientRuntimeStatus | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)