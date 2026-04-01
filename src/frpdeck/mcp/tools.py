"""MCP tool registration over the proxy facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from frpdeck.domain.facade_models import FacadeResult
from frpdeck.facade.proxy_facade import ProxyFacade
from frpdeck.mcp.serialization import MCP_SCHEMA_VERSION, internal_error_result, resolve_instance_dir, to_jsonable
from frpdeck.services.audit import audit_actor


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


def _safe_facade_call(
    operation: str,
    instance_dir: str | Path,
    call: Any,
    *,
    audit_source: str = "cli",
    audit_meta: dict[str, Any] | None = None,
) -> FacadeResult:
    """Collapse unexpected adapter failures into a stable MCP response."""
    try:
        with audit_actor(audit_source, **(audit_meta or {})):
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


ToolShape = Literal["instance_only", "name", "proxy_spec", "update", "remove", "reload"]
ToolArgs = tuple[Any, ...]
ToolKwargs = dict[str, Any] | None
ToolInvoker = Callable[[str | Path, ToolArgs, ToolKwargs], FacadeResult]
ToolWrapperBuilder = Callable[[Path | None, ToolInvoker], Callable[..., FacadeResult]]


@dataclass(slots=True, frozen=True)
class ToolSpec:
    name: str
    operation: str
    description: str
    shape: ToolShape
    caller_name: str


_TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("list_proxies", "list_proxies", "List proxies from proxies.yaml for an instance directory.", "instance_only", "list_proxies_tool"),
    ToolSpec("get_proxy", "get_proxy", "Get a single proxy by name from proxies.yaml.", "name", "get_proxy_tool"),
    ToolSpec("add_proxy", "add_proxy", "Add a structured proxy spec to proxies.yaml.", "proxy_spec", "add_proxy_tool"),
    ToolSpec("update_proxy", "update_proxy", "Apply a structured patch to an existing proxy.", "update", "update_proxy_tool"),
    ToolSpec("remove_proxy", "remove_proxy", "Remove a proxy, soft-disabling it by default.", "remove", "remove_proxy_tool"),
    ToolSpec("enable_proxy", "enable_proxy", "Enable a proxy in proxies.yaml.", "name", "enable_proxy_tool"),
    ToolSpec("disable_proxy", "disable_proxy", "Disable a proxy in proxies.yaml.", "name", "disable_proxy_tool"),
    ToolSpec("validate_proxy_set", "validate_proxy_set", "Validate the current proxy set for an instance.", "instance_only", "validate_proxy_set_tool"),
    ToolSpec("preview_proxy_changes", "preview_proxy_changes", "Preview rendered proxy outputs without mutating rendered/.", "instance_only", "preview_proxy_changes_tool"),
    ToolSpec("apply_proxy_changes", "apply_proxy_changes", "Validate, render, sync, and optionally reload client proxy changes.", "reload", "apply_proxy_changes_tool"),
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
    audit_meta = {"mode": mode, "server_name": server_name}

    def server_info() -> ServerInfoResult:
        """Return lightweight MCP diagnostic information for this server instance."""
        return _server_info(mode, bound_instance_dir, server_name=server_name)

    server.add_tool(
        server_info,
        name="server_info",
        description="Return lightweight MCP diagnostic information for this server instance.",
    )

    if mode == "bound" and bound_instance_dir is None:
        raise ValueError("bound MCP mode requires a bound_instance_dir")

    for spec in _TOOL_SPECS:
        server.add_tool(
            _build_tool_wrapper(
                spec,
                facade=tool_facade,
                mode=mode,
                bound_instance_dir=bound_instance_dir,
                audit_meta=audit_meta,
            ),
            name=spec.name,
            description=spec.description,
        )


def _build_tool_wrapper(
    spec: ToolSpec,
    *,
    facade: ProxyFacade,
    mode: str,
    bound_instance_dir: Path | None,
    audit_meta: dict[str, Any],
):
    if mode == "bound":
        assert bound_instance_dir is not None

    def invoke(instance_dir: str | Path, args: ToolArgs = (), kwargs: ToolKwargs = None) -> FacadeResult:
        return _call_tool(
            spec,
            instance_dir,
            facade=facade,
            audit_meta=audit_meta,
            args=args,
            kwargs=kwargs,
        )

    try:
        builder = _SHAPE_BUILDERS[spec.shape]
    except KeyError as exc:
        raise ValueError(f"unsupported MCP tool shape: {spec.shape}") from exc
    return builder(bound_instance_dir, invoke)


def _call_tool(
    spec: ToolSpec,
    instance_dir: str | Path,
    *,
    facade: ProxyFacade,
    audit_meta: dict[str, Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> FacadeResult:
    caller = _resolve_tool_caller(spec)
    return _safe_facade_call(
        spec.operation,
        instance_dir,
        lambda: caller(instance_dir, *args, facade=facade, **(kwargs or {})),
        audit_source="mcp",
        audit_meta=audit_meta,
    )


def _resolve_tool_caller(spec: ToolSpec) -> Callable[..., FacadeResult]:
    caller = globals().get(spec.caller_name)
    if not callable(caller):
        raise RuntimeError(f"invalid MCP tool caller: {spec.caller_name}")
    return caller


def _build_instance_only_tool(bound_instance_dir: Path | None, invoke: ToolInvoker):
    if bound_instance_dir is not None:
        def tool() -> FacadeResult:
            return invoke(bound_instance_dir)

        return tool

    def tool(instance_dir: str) -> FacadeResult:
        return invoke(instance_dir)

    return tool


def _build_name_tool(bound_instance_dir: Path | None, invoke: ToolInvoker):
    if bound_instance_dir is not None:
        def tool(name: str) -> FacadeResult:
            return invoke(bound_instance_dir, (name,))

        return tool

    def tool(instance_dir: str, name: str) -> FacadeResult:
        return invoke(instance_dir, (name,))

    return tool


def _build_proxy_spec_tool(bound_instance_dir: Path | None, invoke: ToolInvoker):
    if bound_instance_dir is not None:
        def tool(proxy_spec: dict[str, Any]) -> FacadeResult:
            return invoke(bound_instance_dir, (proxy_spec,))

        return tool

    def tool(instance_dir: str, proxy_spec: dict[str, Any]) -> FacadeResult:
        return invoke(instance_dir, (proxy_spec,))

    return tool


def _build_update_tool(bound_instance_dir: Path | None, invoke: ToolInvoker):
    if bound_instance_dir is not None:
        def tool(name: str, patch_spec: dict[str, Any]) -> FacadeResult:
            return invoke(bound_instance_dir, (name, patch_spec))

        return tool

    def tool(instance_dir: str, name: str, patch_spec: dict[str, Any]) -> FacadeResult:
        return invoke(instance_dir, (name, patch_spec))

    return tool


def _build_remove_tool(bound_instance_dir: Path | None, invoke: ToolInvoker):
    if bound_instance_dir is not None:
        def tool(name: str, soft: bool = True) -> FacadeResult:
            return invoke(bound_instance_dir, (name,), {"soft": soft})

        return tool

    def tool(instance_dir: str, name: str, soft: bool = True) -> FacadeResult:
        return invoke(instance_dir, (name,), {"soft": soft})

    return tool


def _build_reload_tool(bound_instance_dir: Path | None, invoke: ToolInvoker):
    if bound_instance_dir is not None:
        def tool(reload: bool = True) -> FacadeResult:
            return invoke(bound_instance_dir, (), {"reload": reload})

        return tool

    def tool(instance_dir: str, reload: bool = True) -> FacadeResult:
        return invoke(instance_dir, (), {"reload": reload})

    return tool


_SHAPE_BUILDERS: dict[ToolShape, ToolWrapperBuilder] = {
    "instance_only": _build_instance_only_tool,
    "name": _build_name_tool,
    "proxy_spec": _build_proxy_spec_tool,
    "update": _build_update_tool,
    "remove": _build_remove_tool,
    "reload": _build_reload_tool,
}
