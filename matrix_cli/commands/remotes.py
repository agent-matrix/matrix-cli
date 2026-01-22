from __future__ import annotations
import typer
from ..config import load_config, client_from_config
from ..util.console import success
from ..util.operator import require_operator_token

app = typer.Typer(help="Manage Hub remotes")


@app.command("list")
def list_remotes():
    cfg = load_config()
    # If your Matrix-Hub keeps /catalog/remotes admin-only, require token here.
    # If you later make remotes list public, you can remove this line safely.
    require_operator_token(cfg)
    c = client_from_config(cfg)
    print(c.list_remotes())


@app.command("add")
def add_remote(url: str, name: str | None = typer.Option(None, "--name")):
    cfg = load_config()
    require_operator_token(cfg)
    c = client_from_config(cfg)
    print(c.add_remote(url, name=name))
    success("Added remote.")


@app.command("remove")
def remove_remote(name: str):
    cfg = load_config()
    require_operator_token(cfg)
    c = client_from_config(cfg)
    print(c.delete_remote(name))
    success("Removed remote.")


@app.command("ingest")
def ingest(name: str):
    cfg = load_config()
    require_operator_token(cfg)
    c = client_from_config(cfg)
    print(c.trigger_ingest(name))
    success("Ingest triggered.")
