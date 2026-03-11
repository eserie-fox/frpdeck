"""MCP tool registration over the proxy facade."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from frpdeck.domain.facade_models import FacadeResult
from frpdeck.facade.proxy_facade import ProxyFacade
from frpdeck.mcp.serialization import resolve_instance_dir


def list_proxies_tool(instance_dir: str, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).list_proxies(resolve_instance_dir(instance_dir))


def get_proxy_tool(instance_dir: str, name: str, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).get_proxy(resolve_instance_dir(instance_dir), name)


def add_proxy_tool(instance_dir: str, proxy_spec: dict[str, Any], *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).add_proxy(resolve_instance_dir(instance_dir), proxy_spec)


def update_proxy_tool(
    instance_dir: str,
    name: str,
    patch_spec: dict[str, Any],
    *,
    facade: ProxyFacade | None = None,
) -> FacadeResult:
    return (facade or ProxyFacade()).update_proxy(resolve_instance_dir(instance_dir), name, patch_spec)


def remove_proxy_tool(
    instance_dir: str,
    name: str,
    soft: bool = True,
    *,
    facade: ProxyFacade | None = None,
) -> FacadeResult:
    return (facade or ProxyFacade()).remove_proxy(resolve_instance_dir(instance_dir), name, soft=soft)


def enable_proxy_tool(instance_dir: str, name: str, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).enable_proxy(resolve_instance_dir(instance_dir), name)


def disable_proxy_tool(instance_dir: str, name: str, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).disable_proxy(resolve_instance_dir(instance_dir), name)


def validate_proxy_set_tool(instance_dir: str, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).validate_proxy_set(resolve_instance_dir(instance_dir))


def preview_proxy_changes_tool(instance_dir: str, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).preview_proxy_changes(resolve_instance_dir(instance_dir))


def apply_proxy_changes_tool(
    instance_dir: str,
    reload: bool = True,
    *,
    facade: ProxyFacade | None = None,
) -> FacadeResult:
    return (facade or ProxyFacade()).apply_proxy_changes(resolve_instance_dir(instance_dir), reload=reload)


def register_tools(server: FastMCP, facade: ProxyFacade | None = None) -> None:
    """Register structured proxy tools on the MCP server."""
    tool_facade = facade or ProxyFacade()

    @server.tool()
    def list_proxies(instance_dir: str) -> FacadeResult:
        """List proxies from proxies.yaml for an instance directory."""
        return list_proxies_tool(instance_dir, facade=tool_facade)

    @server.tool()
    def get_proxy(instance_dir: str, name: str) -> FacadeResult:
        """Get a single proxy by name from proxies.yaml."""
        return get_proxy_tool(instance_dir, name, facade=tool_facade)

    @server.tool()
    def add_proxy(instance_dir: str, proxy_spec: dict[str, Any]) -> FacadeResult:
        """Add a structured proxy spec to proxies.yaml."""
        return add_proxy_tool(instance_dir, proxy_spec, facade=tool_facade)

    @server.tool()
    def update_proxy(instance_dir: str, name: str, patch_spec: dict[str, Any]) -> FacadeResult:
        """Apply a structured patch to an existing proxy."""
        return update_proxy_tool(instance_dir, name, patch_spec, facade=tool_facade)

    @server.tool()
    def remove_proxy(instance_dir: str, name: str, soft: bool = True) -> FacadeResult:
        """Remove a proxy, soft-disabling it by default."""
        return remove_proxy_tool(instance_dir, name, soft=soft, facade=tool_facade)

    @server.tool()
    def enable_proxy(instance_dir: str, name: str) -> FacadeResult:
        """Enable a proxy in proxies.yaml."""
        return enable_proxy_tool(instance_dir, name, facade=tool_facade)

    @server.tool()
    def disable_proxy(instance_dir: str, name: str) -> FacadeResult:
        """Disable a proxy in proxies.yaml."""
        return disable_proxy_tool(instance_dir, name, facade=tool_facade)

    @server.tool()
    def validate_proxy_set(instance_dir: str) -> FacadeResult:
        """Validate the current proxy set for an instance."""
        return validate_proxy_set_tool(instance_dir, facade=tool_facade)

    @server.tool()
    def preview_proxy_changes(instance_dir: str) -> FacadeResult:
        """Preview rendered proxy outputs without mutating rendered/."""
        return preview_proxy_changes_tool(instance_dir, facade=tool_facade)

    @server.tool()
    def apply_proxy_changes(instance_dir: str, reload: bool = True) -> FacadeResult:
        """Validate, render, sync, and optionally reload client proxy changes."""
        return apply_proxy_changes_tool(instance_dir, reload=reload, facade=tool_facade)