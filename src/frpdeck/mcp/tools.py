"""MCP tool registration over the proxy facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from frpdeck.domain.facade_models import FacadeResult
from frpdeck.facade.proxy_facade import ProxyFacade
from frpdeck.mcp.serialization import MCP_SCHEMA_VERSION, internal_error_result, resolve_instance_dir, to_jsonable


class ServerInfoResult(BaseModel):
    """Lightweight diagnostic payload for verifying MCP connectivity and mode."""

    schema_version: str = MCP_SCHEMA_VERSION
    ok: bool = True
    mode: str
    bound_instance: str | None = None
    cwd: str
    server_name: str
    error_code: str | None = None
    errors: list[str] = Field(default_factory=list)


def list_proxies_tool(instance_dir: str | Path, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).list_proxies(resolve_instance_dir(instance_dir))


def get_proxy_tool(instance_dir: str | Path, name: str, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).get_proxy(resolve_instance_dir(instance_dir), name)


def add_proxy_tool(instance_dir: str | Path, proxy_spec: dict[str, Any], *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).add_proxy(resolve_instance_dir(instance_dir), proxy_spec)


def update_proxy_tool(
    instance_dir: str | Path,
    name: str,
    patch_spec: dict[str, Any],
    *,
    facade: ProxyFacade | None = None,
) -> FacadeResult:
    return (facade or ProxyFacade()).update_proxy(resolve_instance_dir(instance_dir), name, patch_spec)


def remove_proxy_tool(
    instance_dir: str | Path,
    name: str,
    soft: bool = True,
    *,
    facade: ProxyFacade | None = None,
) -> FacadeResult:
    return (facade or ProxyFacade()).remove_proxy(resolve_instance_dir(instance_dir), name, soft=soft)


def enable_proxy_tool(instance_dir: str | Path, name: str, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).enable_proxy(resolve_instance_dir(instance_dir), name)


def disable_proxy_tool(instance_dir: str | Path, name: str, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).disable_proxy(resolve_instance_dir(instance_dir), name)


def validate_proxy_set_tool(instance_dir: str | Path, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).validate_proxy_set(resolve_instance_dir(instance_dir))


def preview_proxy_changes_tool(instance_dir: str | Path, *, facade: ProxyFacade | None = None) -> FacadeResult:
    return (facade or ProxyFacade()).preview_proxy_changes(resolve_instance_dir(instance_dir))


def apply_proxy_changes_tool(
    instance_dir: str | Path,
    reload: bool = True,
    *,
    facade: ProxyFacade | None = None,
) -> FacadeResult:
    return (facade or ProxyFacade()).apply_proxy_changes(resolve_instance_dir(instance_dir), reload=reload)


def _finalize_facade_result(operation: str, instance_dir: str | Path, result: FacadeResult) -> FacadeResult:
    """Ensure tool results remain JSON-serializable after wrapping."""
    try:
        return FacadeResult.model_validate(to_jsonable(result))
    except Exception as exc:
        return internal_error_result(operation, instance_dir, exc)


def _safe_facade_call(operation: str, instance_dir: str | Path, call: Any) -> FacadeResult:
    """Collapse unexpected adapter failures into a stable MCP response."""
    try:
        result = call()
    except Exception as exc:
        return internal_error_result(operation, instance_dir, exc)
    return _finalize_facade_result(operation, instance_dir, result)


def _server_info(mode: str, bound_instance_dir: Path | None, *, server_name: str) -> ServerInfoResult:
    return ServerInfoResult(
        mode=mode,
        bound_instance=None if bound_instance_dir is None else str(bound_instance_dir),
        cwd=str(Path.cwd().resolve()),
        server_name=server_name,
    )


def register_tools(
    server: FastMCP,
    facade: ProxyFacade | None = None,
    *,
    mode: str = "generic",
    bound_instance_dir: Path | None = None,
    server_name: str = "frpdeck",
) -> None:
    """Register structured proxy tools on the MCP server."""
    tool_facade = facade or ProxyFacade()

    @server.tool()
    def server_info() -> ServerInfoResult:
        """Return lightweight MCP diagnostic information for this server instance."""
        return _server_info(mode, bound_instance_dir, server_name=server_name)

    if mode == "bound":
        if bound_instance_dir is None:
            raise ValueError("bound MCP mode requires a bound_instance_dir")

        @server.tool()
        def list_proxies() -> FacadeResult:
            """List proxies from proxies.yaml for the bound instance directory."""
            return _safe_facade_call("list_proxies", bound_instance_dir, lambda: list_proxies_tool(bound_instance_dir, facade=tool_facade))

        @server.tool()
        def get_proxy(name: str) -> FacadeResult:
            """Get a single proxy by name from proxies.yaml."""
            return _safe_facade_call("get_proxy", bound_instance_dir, lambda: get_proxy_tool(bound_instance_dir, name, facade=tool_facade))

        @server.tool()
        def add_proxy(proxy_spec: dict[str, Any]) -> FacadeResult:
            """Add a structured proxy spec to proxies.yaml."""
            return _safe_facade_call("add_proxy", bound_instance_dir, lambda: add_proxy_tool(bound_instance_dir, proxy_spec, facade=tool_facade))

        @server.tool()
        def update_proxy(name: str, patch_spec: dict[str, Any]) -> FacadeResult:
            """Apply a structured patch to an existing proxy."""
            return _safe_facade_call(
                "update_proxy",
                bound_instance_dir,
                lambda: update_proxy_tool(bound_instance_dir, name, patch_spec, facade=tool_facade),
            )

        @server.tool()
        def remove_proxy(name: str, soft: bool = True) -> FacadeResult:
            """Remove a proxy, soft-disabling it by default."""
            return _safe_facade_call(
                "remove_proxy",
                bound_instance_dir,
                lambda: remove_proxy_tool(bound_instance_dir, name, soft=soft, facade=tool_facade),
            )

        @server.tool()
        def enable_proxy(name: str) -> FacadeResult:
            """Enable a proxy in proxies.yaml."""
            return _safe_facade_call("enable_proxy", bound_instance_dir, lambda: enable_proxy_tool(bound_instance_dir, name, facade=tool_facade))

        @server.tool()
        def disable_proxy(name: str) -> FacadeResult:
            """Disable a proxy in proxies.yaml."""
            return _safe_facade_call("disable_proxy", bound_instance_dir, lambda: disable_proxy_tool(bound_instance_dir, name, facade=tool_facade))

        @server.tool()
        def validate_proxy_set() -> FacadeResult:
            """Validate the current proxy set for the bound instance."""
            return _safe_facade_call(
                "validate_proxy_set",
                bound_instance_dir,
                lambda: validate_proxy_set_tool(bound_instance_dir, facade=tool_facade),
            )

        @server.tool()
        def preview_proxy_changes() -> FacadeResult:
            """Preview rendered proxy outputs without mutating rendered/."""
            return _safe_facade_call(
                "preview_proxy_changes",
                bound_instance_dir,
                lambda: preview_proxy_changes_tool(bound_instance_dir, facade=tool_facade),
            )

        @server.tool()
        def apply_proxy_changes(reload: bool = True) -> FacadeResult:
            """Validate, render, sync, and optionally reload client proxy changes."""
            return _safe_facade_call(
                "apply_proxy_changes",
                bound_instance_dir,
                lambda: apply_proxy_changes_tool(bound_instance_dir, reload=reload, facade=tool_facade),
            )
        return

    @server.tool()
    def list_proxies(instance_dir: str) -> FacadeResult:
        """List proxies from proxies.yaml for an instance directory."""
        return _safe_facade_call("list_proxies", instance_dir, lambda: list_proxies_tool(instance_dir, facade=tool_facade))

    @server.tool()
    def get_proxy(instance_dir: str, name: str) -> FacadeResult:
        """Get a single proxy by name from proxies.yaml."""
        return _safe_facade_call("get_proxy", instance_dir, lambda: get_proxy_tool(instance_dir, name, facade=tool_facade))

    @server.tool()
    def add_proxy(instance_dir: str, proxy_spec: dict[str, Any]) -> FacadeResult:
        """Add a structured proxy spec to proxies.yaml."""
        return _safe_facade_call("add_proxy", instance_dir, lambda: add_proxy_tool(instance_dir, proxy_spec, facade=tool_facade))

    @server.tool()
    def update_proxy(instance_dir: str, name: str, patch_spec: dict[str, Any]) -> FacadeResult:
        """Apply a structured patch to an existing proxy."""
        return _safe_facade_call(
            "update_proxy",
            instance_dir,
            lambda: update_proxy_tool(instance_dir, name, patch_spec, facade=tool_facade),
        )

    @server.tool()
    def remove_proxy(instance_dir: str, name: str, soft: bool = True) -> FacadeResult:
        """Remove a proxy, soft-disabling it by default."""
        return _safe_facade_call(
            "remove_proxy",
            instance_dir,
            lambda: remove_proxy_tool(instance_dir, name, soft=soft, facade=tool_facade),
        )

    @server.tool()
    def enable_proxy(instance_dir: str, name: str) -> FacadeResult:
        """Enable a proxy in proxies.yaml."""
        return _safe_facade_call("enable_proxy", instance_dir, lambda: enable_proxy_tool(instance_dir, name, facade=tool_facade))

    @server.tool()
    def disable_proxy(instance_dir: str, name: str) -> FacadeResult:
        """Disable a proxy in proxies.yaml."""
        return _safe_facade_call("disable_proxy", instance_dir, lambda: disable_proxy_tool(instance_dir, name, facade=tool_facade))

    @server.tool()
    def validate_proxy_set(instance_dir: str) -> FacadeResult:
        """Validate the current proxy set for an instance."""
        return _safe_facade_call("validate_proxy_set", instance_dir, lambda: validate_proxy_set_tool(instance_dir, facade=tool_facade))

    @server.tool()
    def preview_proxy_changes(instance_dir: str) -> FacadeResult:
        """Preview rendered proxy outputs without mutating rendered/."""
        return _safe_facade_call(
            "preview_proxy_changes",
            instance_dir,
            lambda: preview_proxy_changes_tool(instance_dir, facade=tool_facade),
        )

    @server.tool()
    def apply_proxy_changes(instance_dir: str, reload: bool = True) -> FacadeResult:
        """Validate, render, sync, and optionally reload client proxy changes."""
        return _safe_facade_call(
            "apply_proxy_changes",
            instance_dir,
            lambda: apply_proxy_changes_tool(instance_dir, reload=reload, facade=tool_facade),
        )