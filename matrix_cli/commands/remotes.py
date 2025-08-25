from __future__ import annotations
import typer
from ..config import load_config, client_from_config
from ..util.console import success

app = typer.Typer(help="Manage Hub remotes")


@app.command("list")
def list_remotes():
    c = client_from_config(load_config())
    print(c.list_remotes())


@app.command("add")
def add_remote(url: str, name: str | None = typer.Option(None, "--name")):
    c = client_from_config(load_config())
    print(c.add_remote(url, name=name))
    success("Added remote.")


@app.command("remove")
def remove_remote(name: str):
    c = client_from_config(load_config())
    print(c.delete_remote(name))
    success("Removed remote.")


@app.command("ingest")
def ingest(name: str):
    c = client_from_config(load_config())
    print(c.trigger_ingest(name))
    success("Ingest triggered.")
