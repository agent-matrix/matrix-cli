from __future__ import annotations
import typer
from ..util.console import success, error

app = typer.Typer(help="Stop a running server")


@app.command()
def main(alias: str):
    from matrix_sdk import runtime

    if runtime.stop(alias):
        success(f"Stopped server for alias '{alias}'.")
    else:
        error(f"Server for alias '{alias}' was not running.")
        raise typer.Exit(1)
