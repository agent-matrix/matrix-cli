# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.json import JSON
from rich.table import Table

from matrix_sdk.client import MatrixClient, MatrixAPIError
from matrix_sdk.cache import Cache

from ..config import MatrixCLIConfig

app = typer.Typer(help="Manage Matrix Hub catalog remotes.")


def _make_client(cfg: MatrixCLIConfig) -> MatrixClient:
    cache = Cache(cache_dir=cfg.cache_dir, ttl=cfg.cache_ttl)
    return MatrixClient(cfg.registry_url, token=cfg.registry_token, cache=cache)


@app.command("list")
def list_remotes(ctx: typer.Context, json_out: bool = typer.Option(False, "--json")) -> None:
    """
    matrix remotes list
    """
    console = Console()
    cfg: MatrixCLIConfig = ctx.obj
    client = _make_client(cfg)
    try:
        res = client.list_remotes()
        if json_out:
            console.print(JSON.from_data(res))
            raise typer.Exit(0)

        items = res if isinstance(res, list) else res.get("items", res) or []
        if not items:
            console.print("[yellow]No remotes configured.[/]")
            raise typer.Exit(0)

        t = Table(title="Catalog remotes")
        t.add_column("Name")
        t.add_column("URL", overflow="fold")
        t.add_column("Last Sync")
        t.add_column("ETag", overflow="fold")
        for r in items:
            t.add_row(str(r.get("name", "")), str(r.get("url", "")), str(r.get("last_sync_ts", "") or ""), str(r.get("etag", "") or ""))
        console.print(t)

    except MatrixAPIError as e:
        console.print(f"[red]API error ({e.status_code}):[/] {e.body or e}", highlight=False)
        raise typer.Exit(1)
    except Exception as e:  # pragma: no cover
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


@app.command("add")
def add_remote(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="Remote catalog URL (e.g., index.json)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Friendly name"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """
    matrix remotes add https://raw.githubusercontent.com/agent-matrix/catalog/main/index.json --name catalogs
    """
    console = Console()
    cfg: MatrixCLIConfig = ctx.obj
    client = _make_client(cfg)
    try:
        res = client.add_remote(url=url, name=name)
        if json_out:
            console.print(JSON.from_data(res))
        else:
            console.print(f"[green]Added remote:[/] {name or '(unnamed)'} → {url}")
    except MatrixAPIError as e:
        console.print(f"[red]API error ({e.status_code}):[/] {e.body or e}", highlight=False)
        raise typer.Exit(1)
    except Exception as e:  # pragma: no cover
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


@app.command("ingest")
def ingest_remote(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Name of the remote"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """
    matrix remotes ingest <name>
    """
    console = Console()
    cfg: MatrixCLIConfig = ctx.obj
    client = _make_client(cfg)
    try:
        res = client.trigger_ingest(name)
        if json_out:
            console.print(JSON.from_data(res))
        else:
            console.print(f"[green]Triggered ingest for remote:[/] {name}")
    except MatrixAPIError as e:
        console.print(f"[red]API error ({e.status_code}):[/] {e.body or e}", highlight=False)
        raise typer.Exit(1)
    except Exception as e:  # pragma: no cover
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
