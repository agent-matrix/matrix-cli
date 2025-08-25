from __future__ import annotations
import json
import typer
from ..util.console import success, error

app = typer.Typer(help="Manage local component aliases")


@app.command("list")
def list_aliases():
    from matrix_sdk.alias import AliasStore

    items = AliasStore().all()
    for name, meta in sorted(items.items()):
        print(f"{name:24s} {meta.get('id', '-'):36s} {meta.get('target', '-')}")


@app.command("show")
def show_alias(alias: str):
    from matrix_sdk.alias import AliasStore

    rec = AliasStore().get(alias)
    if not rec:
        error(f"Alias '{alias}' not found.")
        raise typer.Exit(1)
    print(json.dumps(rec, indent=2))


@app.command("rm")
def remove_alias(
    alias: str, yes: bool = typer.Option(False, "--yes", "-y", help="Confirm removal")
):
    from matrix_sdk.alias import AliasStore

    if not yes and not typer.confirm(
        f"Are you sure you want to remove alias '{alias}'?"
    ):
        raise typer.Exit(1)
    if AliasStore().remove(alias):
        success(f"Removed alias '{alias}'.")
    else:
        error(f"Alias '{alias}' not found.")
        raise typer.Exit(1)


@app.command("add")
def add_alias(alias: str, id: str, target: str):
    from matrix_sdk.alias import AliasStore

    AliasStore().set(alias, id=id, target=target)
    success(f"Added alias '{alias}'.")
