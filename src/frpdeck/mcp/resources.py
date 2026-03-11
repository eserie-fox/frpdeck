"""MCP resources mapped to the read-only status service."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from frpdeck.mcp.serialization import dump_json, resource_error_payload, resolve_instance_dir
from frpdeck.services.status_service import StatusService


def instance_status_resource(instance_dir: str | Path, *, status_service: StatusService | None = None) -> str:
    service = status_service or StatusService()
    try:
        return dump_json(service.get_instance_status(resolve_instance_dir(instance_dir)))
    except Exception as exc:
        return dump_json(resource_error_payload("instance_status", instance_dir, exc))


def proxy_runtime_status_resource(instance_dir: str | Path, *, status_service: StatusService | None = None) -> str:
    service = status_service or StatusService()
    try:
        return dump_json(service.get_proxy_runtime_status(resolve_instance_dir(instance_dir)))
    except Exception as exc:
        return dump_json(resource_error_payload("proxy_runtime_status", instance_dir, exc))


def register_resources(
    server: FastMCP,
    status_service: StatusService | None = None,
    *,
    mode: str = "generic",
    bound_instance_dir: Path | None = None,
) -> None:
    """Register read-only status resources on the MCP server."""
    resource_service = status_service or StatusService()

    if mode == "bound":
        if bound_instance_dir is None:
            raise ValueError("bound MCP mode requires a bound_instance_dir")

        @server.resource("frpdeck://instance/status")
        def read_instance_status() -> str:
            """Read aggregated instance status as JSON text for the bound instance."""
            return instance_status_resource(bound_instance_dir, status_service=resource_service)

        @server.resource("frpdeck://instance/proxy-runtime-status")
        def read_proxy_runtime_status() -> str:
            """Read per-proxy runtime and render status as JSON text for the bound instance."""
            return proxy_runtime_status_resource(bound_instance_dir, status_service=resource_service)
        return

    @server.resource("frpdeck://instance/status?instance={instance_dir}")
    def read_instance_status(instance_dir: str) -> str:
        """Read aggregated instance status as JSON text."""
        return instance_status_resource(instance_dir, status_service=resource_service)

    @server.resource("frpdeck://instance/proxy-runtime-status?instance={instance_dir}")
    def read_proxy_runtime_status(instance_dir: str) -> str:
        """Read per-proxy runtime and render status as JSON text."""
        return proxy_runtime_status_resource(instance_dir, status_service=resource_service)