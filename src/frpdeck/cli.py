"""CLI entrypoint."""

from __future__ import annotations

import typer

from frpdeck.commands import apply, check_update, doctor, init, mcp, proxy, reload, render, restart, status, uninstall, upgrade, validate
from frpdeck.version import __version__


app = typer.Typer(
    help="Structured FRP deployment and maintenance CLI",
    invoke_without_command=True,
)


@app.callback()
def callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit", is_eager=True),
) -> None:
    """Top-level CLI callback."""
    if version:
        typer.echo(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


for module in [init, render, validate, apply, reload, restart, status, uninstall, check_update, upgrade, doctor, proxy, mcp]:
    module.register(app)


def main() -> None:
    app()
