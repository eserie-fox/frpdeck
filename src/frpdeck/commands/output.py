"""CLI output helpers for stable JSON responses."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel

from frpdeck.domain.proxy import HttpProxyConfig, HttpsProxyConfig, ProxyConfig, TcpProxyConfig, UdpProxyConfig
from frpdeck.domain.proxy_management import ApplyReport, PreviewReport, ProxyMutationResult, ValidationReport


def emit_json_envelope(
    *,
    command: str,
    instance: Path,
    ok: bool,
    data: Any,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> None:
    """Emit a stable JSON envelope for programmatic consumers."""
    typer.echo(
        json.dumps(
            {
                "ok": ok,
                "command": command,
                "instance": str(instance.resolve()),
                "data": json_ready(data),
                "errors": list(errors or []),
                "warnings": list(warnings or []),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )


def json_ready(value: Any) -> Any:
    """Convert supported objects into JSON-serializable data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return json_ready(value.model_dump(mode="json", exclude_none=False))
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    raise TypeError(f"unsupported JSON serialization type: {type(value).__name__}")


def serialize_proxy(proxy: ProxyConfig) -> dict[str, Any]:
    """Return a stable machine-readable proxy representation."""
    transport = {
        "use_encryption": proxy.transport.use_encryption,
        "use_compression": proxy.transport.use_compression,
        "bandwidth_limit": proxy.transport.bandwidth_limit,
        "bandwidth_limit_mode": proxy.transport.bandwidth_limit_mode.value if proxy.transport.bandwidth_limit_mode else None,
    }
    return {
        "name": proxy.name,
        "enabled": proxy.enabled,
        "type": proxy.type.value,
        "description": proxy.description,
        "local_ip": proxy.local_ip,
        "local_port": proxy.local_port,
        "remote_port": proxy.remote_port if isinstance(proxy, (TcpProxyConfig, UdpProxyConfig)) else None,
        "custom_domains": list(proxy.custom_domains) if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)) else [],
        "subdomain": proxy.subdomain if isinstance(proxy, (HttpProxyConfig, HttpsProxyConfig)) else None,
        "annotations": dict(proxy.annotations),
        "metadatas": dict(proxy.metadatas),
        "transport": transport,
    }


def serialize_validation_report(report: ValidationReport) -> dict[str, Any]:
    """Return a stable validation payload."""
    return {
        "ok": report.ok,
        "error_count": len(report.errors),
        "warning_count": len(report.warnings),
        "errors": list(report.errors),
        "warnings": list(report.warnings),
    }


def serialize_preview_report(report: PreviewReport) -> dict[str, Any]:
    """Return a stable preview payload."""
    return {
        "valid": report.ok,
        "enabled_proxies": list(report.enabled_proxies),
        "disabled_proxies": list(report.disabled_proxies),
        "rendered_files": list(report.rendered_proxy_files),
        "errors": list(report.errors),
        "warnings": list(report.warnings),
    }


def serialize_apply_report(report: ApplyReport, *, applied_proxies: list[str] | None = None) -> dict[str, Any]:
    """Return a stable apply payload."""
    return {
        "success": report.ok,
        "step": report.step,
        "reloaded": report.reloaded,
        "reload_requested": report.reload_requested,
        "reload_output": report.reload_output,
        "rendered_files": list(report.rendered_proxy_files),
        "applied_proxies": list(applied_proxies or []),
        "errors": list(report.errors),
        "warnings": list(report.warnings),
    }


def serialize_mutation_result(result: ProxyMutationResult) -> dict[str, Any]:
    """Return a stable mutation payload."""
    return {
        "operation": result.operation,
        "changed": result.changed,
        "apply_required": result.apply_required,
        "removed_name": result.removed_name,
        "message": result.message,
        "proxy": serialize_proxy(result.proxy) if result.proxy is not None else None,
        "warnings": list(result.warnings),
    }