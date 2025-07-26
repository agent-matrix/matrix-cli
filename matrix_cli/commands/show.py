# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

from matrix_sdk.client import MatrixClient, MatrixAPIError
from matrix_sdk.cache import Cache

from ..config import MatrixCLIConfig

app = typer.Typer(help="Show entity details.")


def _make_client(cfg: MatrixCLIConfig) -> MatrixClient:
    cache = Cache(cache_dir=cfg.cache_dir, ttl=cfg.cache_ttl)
    return MatrixClient(cfg.registry_url, token=cfg.registry_token, cache=cache)


@app.command("run")
def show_cmd(
    ctx: typer.Context,
    id: str = typer.Argument(..., help="Entity UID, e.g. agent:pdf-summarizer@1.4.2"),
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSON"),
) -> None:
    """
    matrix show agent:pdf-summarizer@1.4.2
    """
    console = Console()
    cfg: MatrixCLIConfig = ctx.obj
    client = _make_client(cfg)

    try:
        ent = client.get_entity(id)
        if json_out:
            console.print(JSON.from_data(ent))
            raise typer.Exit(0)

        data = ent if isinstance(ent, dict) else ent.model_dump()

        # Header
        title = f"{data.get('id','')} — {data.get('name','')} ({data.get('version','')})"
        console.print(Panel(title, title="Entity", subtitle=data.get("type", "")))

        # Summary table
        tbl = Table(show_header=False)
        tbl.add_row("Type", data.get("type", ""))
        tbl.add_row("Summary", data.get("summary", "") or data.get("description", "") or "")
        tbl.add_row("Capabilities", ",".join(data.get("capabilities", []) or []))
        tbl.add_row("Frameworks", ",".join(data.get("frameworks", []) or []))
        tbl.add_row("Providers", ",".join(data.get("providers", []) or []))
        if data.get("license"):
            tbl.add_row("License", data.get("license"))
        if data.get("homepage"):
            tbl.add_row("Homepage", data.get("homepage"))
        if data.get("source_url"):
            tbl.add_row("Manifest", data.get("source_url"))
        console.print(tbl)

        # Artifacts/adapters if present
        arts = data.get("artifacts") or []
        if arts:
            at = Table(title="Artifacts")
            at.add_column("Kind")
            at.add_column("Spec", overflow="fold")
            for a in arts:
                at.add_row(str(a.get("kind", "")), str(a.get("spec", "")))
            console.print(at)

        adp = data.get("adapters") or []
        if adp:
            at = Table(title="Adapters")
            at.add_column("Framework")
            at.add_column("Template")
            at.add_column("Params", overflow="fold")
            for a in adp:
                at.add_row(
                    str(a.get("framework", "")),
                    str(a.get("template_key", "")),
                    str(a.get("params", "")),
                )
            console.print(at)

    except MatrixAPIError as e:
        console.print(f"[red]API error ({e.status_code}):[/] {e.body or e}", highlight=False)
        raise typer.Exit(1)
    except Exception as e:  # pragma: no cover
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
