"""MCP resources mapped to the read-only status service."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from frpdeck.mcp.serialization import dump_json, resolve_instance_dir
from frpdeck.services.status_service import StatusService


def instance_status_resource(instance_dir: str, *, status_service: StatusService | None = None) -> str:
    service = status_service or StatusService()
    return dump_json(service.get_instance_status(resolve_instance_dir(instance_dir)))


def proxy_runtime_status_resource(instance_dir: str, *, status_service: StatusService | None = None) -> str:
    service = status_service or StatusService()
    return dump_json(service.get_proxy_runtime_status(resolve_instance_dir(instance_dir)))


def register_resources(server: FastMCP, status_service: StatusService | None = None) -> None:
    """Register read-only status resources on the MCP server."""
    resource_service = status_service or StatusService()

    @server.resource("frpdeck://instance/status?instance={instance_dir}")
    def read_instance_status(instance_dir: str) -> str:
        """Read aggregated instance status as JSON text."""
        return instance_status_resource(instance_dir, status_service=resource_service)

    @server.resource("frpdeck://instance/proxy-runtime-status?instance={instance_dir}")
    def read_proxy_runtime_status(instance_dir: str) -> str:
        """Read per-proxy runtime and render status as JSON text."""
        return proxy_runtime_status_resource(instance_dir, status_service=resource_service)