# -*- coding: utf-8 -*-
from __future__ import annotations

from enum import Enum
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

from matrix_sdk.client import MatrixClient, MatrixAPIError
from matrix_sdk.cache import Cache

from ..config import MatrixCLIConfig

app = typer.Typer(help="List entities from Matrix Hub or MCP-Gateway.")


class Source(str, Enum):
    hub = "hub"
    gateway = "gateway"


def _make_client(cfg: MatrixCLIConfig) -> MatrixClient:
    cache = Cache(cache_dir=cfg.cache_dir, ttl=cfg.cache_ttl)
    return MatrixClient(cfg.registry_url, token=cfg.registry_token, cache=cache)


def _list_from_gateway(cfg: MatrixCLIConfig, kind: Optional[str]) -> list[dict]:
    """
    Minimal admin listing against MCP-Gateway.

    kind:
      - "tool" -> GET /tools
      - "mcp_server" -> GET /gateways
      - None -> both
    """
    base = cfg.gateway_url.rstrip("/")
    headers = {"Accept": "application/json"}
    if cfg.gateway_token:
        headers["Authorization"] = f"Bearer {cfg.gateway_token}"

    out: list[dict] = []
    with httpx.Client(timeout=15.0, headers=headers) as c:
        if kind in (None, "tool"):
            try:
                r = c.get(f"{base}/tools")
                if r.status_code == 200:
                    out.extend(r.json() or [])
            except Exception:
                pass
        if kind in (None, "mcp_server"):
            try:
                r = c.get(f"{base}/gateways")
                if r.status_code == 200:
                    # Normalize record shape
                    for g in r.json() or []:
                        out.append({"kind": "mcp_server", **g})
            except Exception:
                pass
    return out


@app.command("run")
def list_cmd(
    ctx: typer.Context,
    type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by type: agent|tool|mcp_server"
    ),
    source: Source = typer.Option(
        Source.hub,
        "--source",
        "-s",
        help="Which catalog to list from (hub or gateway)",
    ),
    limit: int = typer.Option(
        100, "--limit", "-n", min=1, max=500, help="Maximum number of items"
    ),
) -> None:
    """
    matrix list --type tool --source gateway
    """
    console = Console()
    cfg: MatrixCLIConfig = ctx.obj

    if source is Source.hub:
        client = _make_client(cfg)
        try:
            # Use '*' as a broad query; backend may interpret it as "match all"
            resp = client.search(q="*", type=type, limit=limit, mode="keyword")
            items = resp["items"] if isinstance(resp, dict) else resp.items

            table = Table(title=f"Hub entities (limit={limit})")
            table.add_column("#", justify="right")
            table.add_column("ID", overflow="fold")
            table.add_column("Name", style="bold")
            table.add_column("Ver")
            table.add_column("Type")
            table.add_column("Caps", overflow="fold")
            for i, it in enumerate(items, start=1):
                row = it if isinstance(it, dict) else it.model_dump()
                table.add_row(
                    str(i),
                    row.get("id", ""),
                    row.get("name", ""),
                    row.get("version", ""),
                    row.get("type", ""),
                    ",".join(row.get("capabilities", []) or []),
                )
            console.print(table)
        except MatrixAPIError as e:
            console.print(f"[red]API error ({e.status_code}):[/] {e.body or e}", highlight=False)
            raise typer.Exit(1)
        except Exception as e:  # pragma: no cover
            console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1)

    else:  # source == Source.gateway
        rows = _list_from_gateway(cfg, kind=type)
        if not rows:
            console.print("[yellow]No entities returned from gateway.[/]")
            raise typer.Exit(0)

        table = Table(title="MCP-Gateway")
        table.add_column("#", justify="right")
        table.add_column("Kind")
        table.add_column("Name", style="bold")
        table.add_column("ID/UID", overflow="fold")
        table.add_column("URL", overflow="fold")

        for i, r in enumerate(rows, start=1):
            kind = r.get("kind") or (
                "tool" if "input_schema" in r or "integration_type" in r else "mcp_server"
            )
            name = r.get("name") or r.get("id") or r.get("uid") or ""
            uid = r.get("uid") or r.get("id") or ""
            url = r.get("url") or r.get("endpoint") or r.get("base_url") or ""
            table.add_row(str(i), str(kind), str(name), str(uid), str(url))
        console.print(table)
