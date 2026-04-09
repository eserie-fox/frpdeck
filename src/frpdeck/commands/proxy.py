"""Structured proxy management commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

import typer
import yaml

from frpdeck.commands._invocation import CommandInvocation, build_command_invocation
from frpdeck.commands._privilege import maybe_reexec_with_sudo, raise_for_missing_privileges, unreadable_path_reason
from frpdeck.commands.output import (
    emit_json_envelope,
    serialize_mutation_result,
    serialize_preview_report,
    serialize_proxy,
)
from frpdeck.domain.errors import (
    ConfigLoadError,
    PermissionOperationError,
    ProxyAlreadyExistsError,
    ProxyConflictError,
    ProxyNotFoundError,
    UnsupportedOperationError,
)
from frpdeck.domain.proxy import ProxyConfig
from frpdeck.domain.proxy_management import PreviewReport, ProxyMutationResult, ProxyUpdatePatch
from frpdeck.logging.daily_symlink import instance_logging_context
from frpdeck.services.proxy_manager import ProxyManager, analyze_proxy_write_root_requirements, load_proxy_spec_from_file


proxy_app = typer.Typer(help="Structured local proxy management", no_args_is_help=True)
proxy_add_app = typer.Typer(help="Add a structured proxy definition", no_args_is_help=True)
proxy_app.add_typer(proxy_add_app, name="add")

MANAGER = ProxyManager()
CommandResult = TypeVar("CommandResult")


@dataclass(slots=True)
class _ProxyCommandContext:
    command: str
    instance_dir: Path
    json_output: bool

    @property
    def stream_override(self) -> str | None:
        return "none" if self.json_output else None


def register(app: typer.Typer) -> None:
    app.add_typer(proxy_app, name="proxy")


@proxy_app.command("list")
def list_command(
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List proxies from proxies.yaml."""
    ctx = _command_context("proxy list", instance, json_output)
    proxies = _run_proxy_action(ctx, lambda: MANAGER.list_proxies(ctx.instance_dir), errors=(ConfigLoadError,))
    _emit_proxy_list(ctx, proxies)


@proxy_app.command("show")
def show_command(
    name: str,
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show a single proxy as YAML."""
    ctx = _command_context("proxy show", instance, json_output)
    proxy = _run_proxy_action(ctx, lambda: MANAGER.get_proxy(ctx.instance_dir, name), errors=(ConfigLoadError, ProxyNotFoundError))
    _emit_proxy_show(ctx, proxy)


@proxy_app.command("import")
def import_command(
    ctx: typer.Context,
    file: Path = typer.Argument(..., exists=True, dir_okay=False, resolve_path=True, help="Proxy spec YAML file"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Import one proxy definition from a YAML file."""
    instance_dir = instance.resolve()
    invocation = build_command_invocation(
        ctx,
        overrides={
            "file": file.resolve(),
            "instance": instance_dir,
        },
    )
    result = _run_proxy_mutation_action(
        command_name="proxy import",
        instance=instance,
        json_output=json_output,
        sudo=sudo,
        invocation=invocation,
        action=lambda: MANAGER.import_proxy_file(instance_dir, file),
        errors=(ConfigLoadError, ProxyAlreadyExistsError, ProxyConflictError),
        extra_read_paths=[("proxy import file", file)],
    )
    if result is None:
        return
    ctx = _command_context("proxy import", instance, json_output)
    _emit_mutation_result(ctx, result)


@proxy_add_app.command("tcp")
def add_tcp_command(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Proxy name"),
    local_ip: str = typer.Option("127.0.0.1", "--local-ip", help="Local IP"),
    local_port: int = typer.Option(..., "--local-port", min=1, max=65535, help="Local port"),
    remote_port: int = typer.Option(..., "--remote-port", min=1, max=65535, help="Remote port"),
    description: str | None = typer.Option(None, "--description", help="Description"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Add a common TCP proxy without a spec file."""
    _add_proxy_command(
        ctx=ctx,
        command_name="proxy add tcp",
        payload={
            "name": name,
            "type": "tcp",
            "local_ip": local_ip,
            "local_port": local_port,
            "remote_port": remote_port,
            "description": description,
        },
        instance=instance,
        json_output=json_output,
        sudo=sudo,
    )


@proxy_add_app.command("udp")
def add_udp_command(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Proxy name"),
    local_ip: str = typer.Option("127.0.0.1", "--local-ip", help="Local IP"),
    local_port: int = typer.Option(..., "--local-port", min=1, max=65535, help="Local port"),
    remote_port: int = typer.Option(..., "--remote-port", min=1, max=65535, help="Remote port"),
    description: str | None = typer.Option(None, "--description", help="Description"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Add a common UDP proxy without a spec file."""
    _add_proxy_command(
        ctx=ctx,
        command_name="proxy add udp",
        payload={
            "name": name,
            "type": "udp",
            "local_ip": local_ip,
            "local_port": local_port,
            "remote_port": remote_port,
            "description": description,
        },
        instance=instance,
        json_output=json_output,
        sudo=sudo,
    )


@proxy_add_app.command("http")
def add_http_command(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Proxy name"),
    local_ip: str = typer.Option("127.0.0.1", "--local-ip", help="Local IP"),
    local_port: int = typer.Option(..., "--local-port", min=1, max=65535, help="Local port"),
    custom_domain: list[str] | None = typer.Option(None, "--custom-domain", help="Custom domain; repeat for multiple domains"),
    subdomain: str | None = typer.Option(None, "--subdomain", help="Subdomain"),
    description: str | None = typer.Option(None, "--description", help="Description"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Add a common HTTP proxy without a spec file."""
    _add_proxy_command(
        ctx=ctx,
        command_name="proxy add http",
        payload={
            "name": name,
            "type": "http",
            "local_ip": local_ip,
            "local_port": local_port,
            "custom_domains": list(custom_domain or []),
            "subdomain": subdomain,
            "description": description,
        },
        instance=instance,
        json_output=json_output,
        sudo=sudo,
    )


@proxy_add_app.command("https")
def add_https_command(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Proxy name"),
    local_ip: str = typer.Option("127.0.0.1", "--local-ip", help="Local IP"),
    local_port: int = typer.Option(..., "--local-port", min=1, max=65535, help="Local port"),
    custom_domain: list[str] | None = typer.Option(None, "--custom-domain", help="Custom domain; repeat for multiple domains"),
    subdomain: str | None = typer.Option(None, "--subdomain", help="Subdomain"),
    description: str | None = typer.Option(None, "--description", help="Description"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Add a common HTTPS proxy without a spec file."""
    _add_proxy_command(
        ctx=ctx,
        command_name="proxy add https",
        payload={
            "name": name,
            "type": "https",
            "local_ip": local_ip,
            "local_port": local_port,
            "custom_domains": list(custom_domain or []),
            "subdomain": subdomain,
            "description": description,
        },
        instance=instance,
        json_output=json_output,
        sudo=sudo,
    )


@proxy_app.command("update")
def update_command(
    ctx: typer.Context,
    name: str,
    file: Path = typer.Argument(..., exists=True, dir_okay=False, resolve_path=True, help="Proxy patch YAML file"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Patch an existing proxy from a YAML file."""
    instance_dir = instance.resolve()
    invocation = build_command_invocation(
        ctx,
        overrides={
            "file": file.resolve(),
            "instance": instance_dir,
        },
    )
    result = _run_proxy_mutation_action(
        command_name="proxy update",
        instance=instance,
        json_output=json_output,
        sudo=sudo,
        invocation=invocation,
        action=lambda: MANAGER.update_proxy(
            instance_dir,
            name,
            ProxyUpdatePatch.model_validate(load_proxy_spec_from_file(file)),
        ),
        errors=(ConfigLoadError, ProxyNotFoundError, ProxyAlreadyExistsError, ProxyConflictError, ValueError),
        extra_read_paths=[("proxy patch file", file)],
    )
    if result is None:
        return
    ctx = _command_context("proxy update", instance, json_output)
    _emit_mutation_result(ctx, result)


@proxy_app.command("enable")
def enable_command(
    ctx: typer.Context,
    name: str,
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Enable a proxy in proxies.yaml."""
    result = _run_proxy_mutation_action(
        command_name="proxy enable",
        instance=instance,
        json_output=json_output,
        sudo=sudo,
        invocation=build_command_invocation(ctx, overrides={"instance": instance.resolve()}),
        action=lambda: MANAGER.enable_proxy(instance.resolve(), name),
        errors=(ConfigLoadError, ProxyNotFoundError),
    )
    if result is None:
        return
    ctx = _command_context("proxy enable", instance, json_output)
    _emit_mutation_result(ctx, result)


@proxy_app.command("disable")
def disable_command(
    ctx: typer.Context,
    name: str,
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Disable a proxy in proxies.yaml."""
    result = _run_proxy_mutation_action(
        command_name="proxy disable",
        instance=instance,
        json_output=json_output,
        sudo=sudo,
        invocation=build_command_invocation(ctx, overrides={"instance": instance.resolve()}),
        action=lambda: MANAGER.disable_proxy(instance.resolve(), name),
        errors=(ConfigLoadError, ProxyNotFoundError),
    )
    if result is None:
        return
    ctx = _command_context("proxy disable", instance, json_output)
    _emit_mutation_result(ctx, result)


@proxy_app.command("remove")
def remove_command(
    ctx: typer.Context,
    name: str,
    hard: bool = typer.Option(False, "--hard", help="Permanently delete instead of soft-disabling"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    sudo: bool = typer.Option(False, "--sudo", help="Re-exec the full command via sudo when root is required"),
) -> None:
    """Remove a proxy, soft by default."""
    result = _run_proxy_mutation_action(
        command_name="proxy remove",
        instance=instance,
        json_output=json_output,
        sudo=sudo,
        invocation=build_command_invocation(ctx, overrides={"instance": instance.resolve()}),
        action=lambda: MANAGER.remove_proxy(instance.resolve(), name, soft=not hard),
        errors=(ConfigLoadError, ProxyNotFoundError),
    )
    if result is None:
        return
    ctx = _command_context("proxy remove", instance, json_output)
    _emit_mutation_result(ctx, result)


@proxy_app.command("preview")
def preview_command(
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Preview proxy render results without touching rendered/."""
    ctx = _command_context("proxy preview", instance, json_output)
    report = _run_proxy_action(
        ctx,
        lambda: MANAGER.preview_proxy_changes(ctx.instance_dir),
        errors=(ConfigLoadError, UnsupportedOperationError),
    )
    _emit_preview_result(ctx, report)


def _command_context(command: str, instance: Path, json_output: bool) -> _ProxyCommandContext:
    return _ProxyCommandContext(command=command, instance_dir=instance.resolve(), json_output=json_output)


def _add_proxy_command(
    *,
    ctx: typer.Context,
    command_name: str,
    payload: dict[str, object],
    instance: Path,
    json_output: bool,
    sudo: bool,
) -> None:
    result = _run_proxy_mutation_action(
        command_name=command_name,
        instance=instance,
        json_output=json_output,
        sudo=sudo,
        invocation=build_command_invocation(ctx, overrides={"instance": instance.resolve()}),
        action=lambda: MANAGER.add_proxy(instance.resolve(), payload),
        errors=(ConfigLoadError, ProxyAlreadyExistsError, ProxyConflictError),
    )
    if result is None:
        return
    ctx = _command_context(command_name, instance, json_output)
    _emit_mutation_result(ctx, result)


def _run_proxy_action(
    ctx: _ProxyCommandContext,
    action: Callable[[], CommandResult],
    *,
    errors: tuple[type[BaseException], ...],
) -> CommandResult:
    try:
        with instance_logging_context(ctx.instance_dir, stream_override=ctx.stream_override):
            return action()
    except errors as exc:
        _fail(ctx.command, ctx.instance_dir, str(exc), json_output=ctx.json_output)


def _run_proxy_mutation_action(
    *,
    command_name: str,
    instance: Path,
    json_output: bool,
    sudo: bool,
    invocation: CommandInvocation,
    action: Callable[[], CommandResult],
    errors: tuple[type[BaseException], ...],
    extra_read_paths: list[tuple[str, Path]] | None = None,
) -> CommandResult | None:
    ctx = _command_context(command_name, instance, json_output)
    try:
        if maybe_reexec_with_sudo(
            operation=command_name,
            sudo_requested=sudo,
            invocation=invocation,
        ):
            return None
        reasons = analyze_proxy_write_root_requirements(ctx.instance_dir)
        for label, path in extra_read_paths or []:
            reason = unreadable_path_reason(path, label=label)
            if reason is not None and reason not in reasons:
                reasons.append(reason)
        raise_for_missing_privileges(
            operation=command_name,
            reasons=reasons,
            invocation=invocation,
        )
        with instance_logging_context(ctx.instance_dir, stream_override=ctx.stream_override):
            return action()
    except errors + (PermissionOperationError,) as exc:
        _fail(command_name, ctx.instance_dir, str(exc), json_output=json_output)


def _emit_proxy_list(ctx: _ProxyCommandContext, proxies: list[ProxyConfig]) -> None:
    if ctx.json_output:
        emit_json_envelope(
            command=ctx.command,
            instance=ctx.instance_dir,
            ok=True,
            data={"count": len(proxies), "proxies": [serialize_proxy(proxy) for proxy in proxies]},
        )
        return
    if not proxies:
        typer.echo("no proxies")
        return
    typer.echo("NAME\tENABLED\tTYPE\tTARGET\tREMOTE\tDESCRIPTION")
    for proxy in proxies:
        target = f"{proxy.local_ip}:{proxy.local_port}"
        remote = _remote_endpoint(proxy)
        typer.echo(
            f"{proxy.name}\t{_bool_text(proxy.enabled)}\t{proxy.type.value}\t{target}\t{remote}\t{proxy.description or ''}"
        )


def _emit_proxy_show(ctx: _ProxyCommandContext, proxy: ProxyConfig) -> None:
    if ctx.json_output:
        emit_json_envelope(command=ctx.command, instance=ctx.instance_dir, ok=True, data={"proxy": serialize_proxy(proxy)})
        return
    typer.echo(yaml.safe_dump(proxy.model_dump(mode="json", exclude_none=True), sort_keys=False).strip())


def _emit_mutation_result(ctx: _ProxyCommandContext, result: ProxyMutationResult) -> None:
    if ctx.json_output:
        emit_json_envelope(
            command=ctx.command,
            instance=ctx.instance_dir,
            ok=True,
            data=serialize_mutation_result(result),
            warnings=result.warnings,
        )
        return
    typer.echo(result.message)
    _emit_warnings(result.warnings)


def _emit_preview_result(ctx: _ProxyCommandContext, report: PreviewReport) -> None:
    if ctx.json_output:
        emit_json_envelope(
            command=ctx.command,
            instance=ctx.instance_dir,
            ok=report.ok,
            data=serialize_preview_report(report),
            errors=report.errors,
            warnings=report.warnings,
        )
        if not report.ok:
            raise typer.Exit(code=1)
        return
    _emit_errors(report.errors)
    _emit_warnings(report.warnings)
    typer.echo(f"enabled: {', '.join(report.enabled_proxies) if report.enabled_proxies else '-'}")
    typer.echo(f"disabled: {', '.join(report.disabled_proxies) if report.disabled_proxies else '-'}")
    typer.echo(f"rendered files: {', '.join(report.rendered_proxy_files) if report.rendered_proxy_files else '-'}")
    if not report.ok:
        raise typer.Exit(code=1)


def _remote_endpoint(proxy: object) -> str:
    if hasattr(proxy, "remote_port"):
        return str(getattr(proxy, "remote_port"))
    custom_domains = getattr(proxy, "custom_domains", None) or []
    subdomain = getattr(proxy, "subdomain", None)
    if custom_domains:
        return ",".join(custom_domains)
    return subdomain or "-"


def _bool_text(value: bool) -> str:
    return "yes" if value else "no"


def _fail(command: str, instance: Path, message: str, *, json_output: bool) -> None:
    if json_output:
        emit_json_envelope(command=command, instance=instance, ok=False, data=None, errors=[message], warnings=[])
    else:
        typer.echo(f"ERROR: {message}")
    raise typer.Exit(code=1)


def _emit_errors(errors: list[str]) -> None:
    for error in errors:
        typer.echo(f"ERROR: {error}")


def _emit_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        typer.echo(f"WARNING: {warning}")
