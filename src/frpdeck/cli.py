"""CLI entrypoint."""

from __future__ import annotations

import logging

import typer

from frpdeck.commands import (
    apply,
    audit,
    check_update,
    doctor,
    init,
    mcp,
    proxy,
    reload,
    render,
    restart,
    status,
    sync,
    uninstall,
    upgrade,
    validate,
)
from frpdeck.logging.daily_symlink import configure_default_logging
from frpdeck.version import __version__

app = typer.Typer(
    help="Structured FRP deployment and maintenance CLI",
    epilog="Typical workflow: init → edit configuration → apply → status",
    invoke_without_command=True,
)


@app.callback()
def callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit", is_eager=True),
) -> None:
    """Top-level CLI callback."""
    configure_default_logging()
    ctx.ensure_object(dict)

    if version:
        typer.echo(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

    logging.getLogger("frpdeck.cli").debug("starting CLI command: %s", ctx.invoked_subcommand)


for module in [
    init,
    apply,
    status,
    proxy,
    validate,
    render,
    sync,
    reload,
    restart,
    doctor,
    check_update,
    upgrade,
    uninstall,
    audit,
    mcp,
]:
    module.register(app)


def main() -> None:
    app()
