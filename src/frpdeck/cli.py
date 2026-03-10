"""CLI entrypoint."""

from __future__ import annotations

import typer

from frpdeck.commands import apply, check_update, doctor, init, reload, render, restart, status, upgrade, validate
from frpdeck.version import __version__


app = typer.Typer(help="Structured FRP deployment and maintenance CLI", invoke_without_command=True)


@app.callback()
def callback(version: bool = typer.Option(False, "--version", help="Show version and exit", is_eager=True)) -> None:
    """Top-level CLI callback."""
    if version:
        typer.echo(__version__)
        raise typer.Exit()


for module in [init, render, validate, apply, reload, restart, status, check_update, upgrade, doctor]:
    module.register(app)


def main() -> None:
    app()
