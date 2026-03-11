"""Structured proxy management commands."""

from __future__ import annotations

from pathlib import Path

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
from frpdeck.domain.proxy import TcpProxyConfig
from frpdeck.domain.proxy_management import ProxyUpdatePatch
from frpdeck.services.proxy_manager import ProxyManager, load_proxy_spec_from_file


proxy_app = typer.Typer(help="Structured local proxy management")
MANAGER = ProxyManager()


def register(app: typer.Typer) -> None:
    app.add_typer(proxy_app, name="proxy")


@proxy_app.command("list")
def list_command(
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List proxies from proxies.yaml."""
    instance_dir = instance.resolve()
    try:
        proxies = MANAGER.list_proxies(instance_dir)
    except ConfigLoadError as exc:
        _fail("proxy list", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(
            command="proxy list",
            instance=instance_dir,
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


@proxy_app.command("show")
def show_command(
    name: str,
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show a single proxy as YAML."""
    instance_dir = instance.resolve()
    try:
        proxy = MANAGER.get_proxy(instance_dir, name)
    except (ConfigLoadError, ProxyNotFoundError) as exc:
        _fail("proxy show", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(command="proxy show", instance=instance_dir, ok=True, data={"proxy": serialize_proxy(proxy)})
        return
    typer.echo(yaml.safe_dump(proxy.model_dump(mode="json", exclude_none=True), sort_keys=False).strip())


@proxy_app.command("add")
def add_command(
    from_file: Path = typer.Option(..., "--from-file", exists=True, dir_okay=False, help="Proxy spec YAML file"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add a proxy from a YAML spec file."""
    instance_dir = instance.resolve()
    try:
        result = MANAGER.add_proxy(instance_dir, load_proxy_spec_from_file(from_file.resolve()))
    except (ConfigLoadError, ProxyAlreadyExistsError, ProxyConflictError) as exc:
        _fail("proxy add", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(command="proxy add", instance=instance_dir, ok=True, data=serialize_mutation_result(result), warnings=result.warnings)
        return
    typer.echo(result.message)
    _emit_warnings(result.warnings)


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
    spec = TcpProxyConfig(
        name=name,
        local_ip=local_ip,
        local_port=local_port,
        remote_port=remote_port,
        description=description,
    )
    instance_dir = instance.resolve()
    try:
        result = MANAGER.add_proxy(instance_dir, spec)
    except (ConfigLoadError, ProxyAlreadyExistsError, ProxyConflictError) as exc:
        _fail("proxy add-tcp", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(command="proxy add-tcp", instance=instance_dir, ok=True, data=serialize_mutation_result(result), warnings=result.warnings)
        return
    typer.echo(result.message)
    _emit_warnings(result.warnings)


@proxy_app.command("update")
def update_command(
    name: str,
    from_file: Path = typer.Option(..., "--from-file", exists=True, dir_okay=False, help="Patch YAML file"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Patch an existing proxy from a YAML file."""
    instance_dir = instance.resolve()
    try:
        patch = ProxyUpdatePatch.model_validate(load_proxy_spec_from_file(from_file.resolve()))
        result = MANAGER.update_proxy(instance_dir, name, patch)
    except (ConfigLoadError, ProxyNotFoundError, ProxyAlreadyExistsError, ProxyConflictError, ValueError) as exc:
        _fail("proxy update", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(command="proxy update", instance=instance_dir, ok=True, data=serialize_mutation_result(result), warnings=result.warnings)
        return
    typer.echo(result.message)
    _emit_warnings(result.warnings)


@proxy_app.command("enable")
def enable_command(
    name: str,
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Enable a proxy in proxies.yaml."""
    instance_dir = instance.resolve()
    try:
        result = MANAGER.enable_proxy(instance_dir, name)
    except (ConfigLoadError, ProxyNotFoundError) as exc:
        _fail("proxy enable", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(command="proxy enable", instance=instance_dir, ok=True, data=serialize_mutation_result(result), warnings=result.warnings)
        return
    typer.echo(result.message)
    _emit_warnings(result.warnings)


@proxy_app.command("disable")
def disable_command(
    name: str,
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Disable a proxy in proxies.yaml."""
    instance_dir = instance.resolve()
    try:
        result = MANAGER.disable_proxy(instance_dir, name)
    except (ConfigLoadError, ProxyNotFoundError) as exc:
        _fail("proxy disable", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(command="proxy disable", instance=instance_dir, ok=True, data=serialize_mutation_result(result), warnings=result.warnings)
        return
    typer.echo(result.message)
    _emit_warnings(result.warnings)


@proxy_app.command("remove")
def remove_command(
    name: str,
    hard: bool = typer.Option(False, "--hard", help="Permanently delete instead of soft-disabling"),
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove a proxy, soft by default."""
    instance_dir = instance.resolve()
    try:
        result = MANAGER.remove_proxy(instance_dir, name, soft=not hard)
    except (ConfigLoadError, ProxyNotFoundError) as exc:
        _fail("proxy remove", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(command="proxy remove", instance=instance_dir, ok=True, data=serialize_mutation_result(result), warnings=result.warnings)
        return
    typer.echo(result.message)
    _emit_warnings(result.warnings)


@proxy_app.command("validate")
def validate_command(
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate only the proxy set in proxies.yaml."""
    instance_dir = instance.resolve()
    try:
        report = MANAGER.validate_proxy_set(instance_dir)
    except ConfigLoadError as exc:
        _fail("proxy validate", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(
            command="proxy validate",
            instance=instance_dir,
            ok=report.ok,
            data=serialize_validation_report(report),
            errors=report.errors,
            warnings=report.warnings,
        )
        if not report.ok:
            raise typer.Exit(code=1)
        return
    if not report.ok:
        for error in report.errors:
            typer.echo(f"ERROR: {error}")
        for warning in report.warnings:
            typer.echo(f"WARNING: {warning}")
        raise typer.Exit(code=1)
    typer.echo("proxy validation passed")


@proxy_app.command("preview")
def preview_command(
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Preview proxy render results without touching rendered/."""
    instance_dir = instance.resolve()
    try:
        report = MANAGER.preview_proxy_changes(instance_dir)
    except (ConfigLoadError, UnsupportedOperationError) as exc:
        _fail("proxy preview", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(
            command="proxy preview",
            instance=instance_dir,
            ok=report.ok,
            data=serialize_preview_report(report),
            errors=report.errors,
            warnings=report.warnings,
        )
        if not report.ok:
            raise typer.Exit(code=1)
        return
    for error in report.errors:
        typer.echo(f"ERROR: {error}")
    for warning in report.warnings:
        typer.echo(f"WARNING: {warning}")
    typer.echo(f"enabled: {', '.join(report.enabled_proxies) if report.enabled_proxies else '-'}")
    typer.echo(f"disabled: {', '.join(report.disabled_proxies) if report.disabled_proxies else '-'}")
    typer.echo(f"rendered files: {', '.join(report.rendered_proxy_files) if report.rendered_proxy_files else '-'}")
    if not report.ok:
        raise typer.Exit(code=1)


@proxy_app.command("apply")
def apply_command(
    instance: Path = typer.Option(Path("."), "--instance", help="Instance directory"),
    no_reload: bool = typer.Option(False, "--no-reload", help="Render and sync runtime config without frpc reload"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate, render, sync runtime config, and optionally reload frpc."""
    instance_dir = instance.resolve()
    try:
        applied_proxies = [proxy.name for proxy in MANAGER.list_proxies(instance_dir) if proxy.enabled]
        report = MANAGER.apply_proxy_changes(instance_dir, reload=not no_reload)
    except (ConfigLoadError, UnsupportedOperationError, ProxyApplyError) as exc:
        _fail("proxy apply", instance_dir, str(exc), json_output=json_output)
    if json_output:
        emit_json_envelope(
            command="proxy apply",
            instance=instance_dir,
            ok=report.ok,
            data=serialize_apply_report(report, applied_proxies=applied_proxies),
            errors=report.errors,
            warnings=report.warnings,
        )
        if not report.ok:
            raise typer.Exit(code=1)
        return
    for error in report.errors:
        typer.echo(f"ERROR: {error}")
    for warning in report.warnings:
        typer.echo(f"WARNING: {warning}")
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


def _emit_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        typer.echo(f"WARNING: {warning}")