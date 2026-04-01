"""Structured proxy management commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

import typer
import yaml

from frpdeck.commands.output import (
    emit_json_envelope,
    serialize_apply_report,
    serialize_mutation_result,
    serialize_preview_report,
    serialize_proxy,
    serialize_validation_report,
)
from frpdeck.domain.errors import (
    ConfigLoadError,
    ProxyAlreadyExistsError,
    ProxyApplyError,
    ProxyConflictError,
    ProxyNotFoundError,
    UnsupportedOperationError,
)
from frpdeck.domain.proxy import ProxyConfig, TcpProxyConfig
from frpdeck.domain.proxy_management import ApplyReport, PreviewReport, ProxyMutationResult, ProxyUpdatePatch, ValidationReport
from frpdeck.logging import instance_logging_context
from frpdeck.services.proxy_manager import ProxyManager, load_proxy_spec_from_file


proxy_app = typer.Typer(help="Structured local proxy management", invoke_without_command=True)
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


@proxy_app.callback()
def proxy_callback(ctx: typer.Context) -> None:
    """Show group help when no proxy subcommand is provided."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


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


@proxy_app.command("add")
def add_command(
    from_file: Path = typer.Option(..., "--from-file", exists=True, dir_okay=False, help="Proxy spec YAML file"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add a proxy from a YAML spec file."""
    ctx = _command_context("proxy add", instance, json_output)
    result = _run_proxy_action(
        ctx,
        lambda: MANAGER.add_proxy(ctx.instance_dir, load_proxy_spec_from_file(from_file.resolve())),
        errors=(ConfigLoadError, ProxyAlreadyExistsError, ProxyConflictError),
    )
    _emit_mutation_result(ctx, result)


@proxy_app.command("add-tcp")
def add_tcp_command(
    name: str = typer.Option(..., "--name", help="Proxy name"),
    local_ip: str = typer.Option("127.0.0.1", "--local-ip", help="Local IP"),
    local_port: int = typer.Option(..., "--local-port", min=1, max=65535, help="Local port"),
    remote_port: int = typer.Option(..., "--remote-port", min=1, max=65535, help="Remote port"),
    description: str | None = typer.Option(None, "--description", help="Description"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add a common TCP proxy without a spec file."""
    ctx = _command_context("proxy add-tcp", instance, json_output)
    spec = TcpProxyConfig(
        name=name,
        local_ip=local_ip,
        local_port=local_port,
        remote_port=remote_port,
        description=description,
    )
    result = _run_proxy_action(
        ctx,
        lambda: MANAGER.add_proxy(ctx.instance_dir, spec),
        errors=(ConfigLoadError, ProxyAlreadyExistsError, ProxyConflictError),
    )
    _emit_mutation_result(ctx, result)


@proxy_app.command("update")
def update_command(
    name: str,
    from_file: Path = typer.Option(..., "--from-file", exists=True, dir_okay=False, help="Patch YAML file"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Patch an existing proxy from a YAML file."""
    ctx = _command_context("proxy update", instance, json_output)

    def action() -> ProxyMutationResult:
        patch = ProxyUpdatePatch.model_validate(load_proxy_spec_from_file(from_file.resolve()))
        return MANAGER.update_proxy(ctx.instance_dir, name, patch)

    result = _run_proxy_action(
        ctx,
        action,
        errors=(ConfigLoadError, ProxyNotFoundError, ProxyAlreadyExistsError, ProxyConflictError, ValueError),
    )
    _emit_mutation_result(ctx, result)


@proxy_app.command("enable")
def enable_command(
    name: str,
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Enable a proxy in proxies.yaml."""
    ctx = _command_context("proxy enable", instance, json_output)
    result = _run_proxy_action(ctx, lambda: MANAGER.enable_proxy(ctx.instance_dir, name), errors=(ConfigLoadError, ProxyNotFoundError))
    _emit_mutation_result(ctx, result)


@proxy_app.command("disable")
def disable_command(
    name: str,
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Disable a proxy in proxies.yaml."""
    ctx = _command_context("proxy disable", instance, json_output)
    result = _run_proxy_action(ctx, lambda: MANAGER.disable_proxy(ctx.instance_dir, name), errors=(ConfigLoadError, ProxyNotFoundError))
    _emit_mutation_result(ctx, result)


@proxy_app.command("remove")
def remove_command(
    name: str,
    hard: bool = typer.Option(False, "--hard", help="Permanently delete instead of soft-disabling"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove a proxy, soft by default."""
    ctx = _command_context("proxy remove", instance, json_output)
    result = _run_proxy_action(
        ctx,
        lambda: MANAGER.remove_proxy(ctx.instance_dir, name, soft=not hard),
        errors=(ConfigLoadError, ProxyNotFoundError),
    )
    _emit_mutation_result(ctx, result)


@proxy_app.command("validate")
def validate_command(
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate only the proxy set in proxies.yaml."""
    ctx = _command_context("proxy validate", instance, json_output)
    report = _run_proxy_action(ctx, lambda: MANAGER.validate_proxy_set(ctx.instance_dir), errors=(ConfigLoadError,))
    _emit_validation_result(ctx, report)


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


@proxy_app.command("apply")
def apply_command(
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    no_reload: bool = typer.Option(False, "--no-reload", help="Render and sync FRP runtime config without frpc reload"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate, render, sync FRP runtime config, and optionally reload frpc."""
    ctx = _command_context("proxy apply", instance, json_output)

    def action() -> tuple[list[str], ApplyReport]:
        applied_proxies = [proxy.name for proxy in MANAGER.list_proxies(ctx.instance_dir) if proxy.enabled]
        report = MANAGER.apply_proxy_changes(ctx.instance_dir, reload=not no_reload)
        return applied_proxies, report

    applied_proxies, report = _run_proxy_action(
        ctx,
        action,
        errors=(ConfigLoadError, UnsupportedOperationError, ProxyApplyError),
    )
    _emit_apply_result(ctx, report, applied_proxies=applied_proxies)


def _command_context(command: str, instance: Path, json_output: bool) -> _ProxyCommandContext:
    return _ProxyCommandContext(command=command, instance_dir=instance.resolve(), json_output=json_output)


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


def _emit_validation_result(ctx: _ProxyCommandContext, report: ValidationReport) -> None:
    if ctx.json_output:
        emit_json_envelope(
            command=ctx.command,
            instance=ctx.instance_dir,
            ok=report.ok,
            data=serialize_validation_report(report),
            errors=report.errors,
            warnings=report.warnings,
        )
        if not report.ok:
            raise typer.Exit(code=1)
        return
    if not report.ok:
        _emit_errors(report.errors)
        _emit_warnings(report.warnings)
        raise typer.Exit(code=1)
    typer.echo("proxy validation passed")


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


def _emit_apply_result(ctx: _ProxyCommandContext, report: ApplyReport, *, applied_proxies: list[str]) -> None:
    if ctx.json_output:
        emit_json_envelope(
            command=ctx.command,
            instance=ctx.instance_dir,
            ok=report.ok,
            data=serialize_apply_report(report, applied_proxies=applied_proxies),
            errors=report.errors,
            warnings=report.warnings,
        )
        if not report.ok:
            raise typer.Exit(code=1)
        return
    _emit_errors(report.errors)
    _emit_warnings(report.warnings)
    if not report.ok:
        raise typer.Exit(code=1)
    typer.echo(f"rendered files: {', '.join(report.rendered_proxy_files) if report.rendered_proxy_files else '-'}")
    typer.echo(f"reload requested: {_bool_text(report.reload_requested)}")
    typer.echo(f"reloaded: {_bool_text(report.reloaded)}")
    if report.reload_output:
        typer.echo(report.reload_output)


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
