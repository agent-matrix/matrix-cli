# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.json import JSON

from matrix_sdk.client import MatrixClient, MatrixAPIError
from matrix_sdk.cache import Cache

from ..config import MatrixCLIConfig

app = typer.Typer(help="Search Matrix Hub catalog.")


def _csv_or_none(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    # normalize commas/spaces
    parts = [p.strip() for p in val.split(",") if p.strip()]
    return ",".join(parts) if parts else None


def _make_client(cfg: MatrixCLIConfig) -> MatrixClient:
    cache = Cache(cache_dir=cfg.cache_dir, ttl=cfg.cache_ttl)
    return MatrixClient(cfg.registry_url, token=cfg.registry_token, cache=cache)


@app.command("run")
def search_cmd(
    ctx: typer.Context,
    q: str = typer.Argument(..., help='Free-text query, e.g. "summarize pdfs"'),
    type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by type: agent|tool|mcp_server"
    ),
    capabilities: Optional[str] = typer.Option(
        None, "--capabilities", "-c", help="CSV list, e.g. pdf,summarize"
    ),
    frameworks: Optional[str] = typer.Option(
        None, "--frameworks", "-f", help="CSV list, e.g. langgraph,crewai"
    ),
    providers: Optional[str] = typer.Option(
        None, "--providers", "-p", help="CSV list, e.g. openai,watsonx"
    ),
    mode: str = typer.Option(
        "hybrid", "--mode", help="Search mode: hybrid|keyword|semantic"
    ),
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=200),
    offset: int = typer.Option(0, "--offset", min=0),
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSON"),
) -> None:
    """
    matrix search "some query" [--type agent|tool|mcp_server]
      [--capabilities a,b] [--frameworks f1,f2] [--providers p1,p2]
      [--mode hybrid|keyword|semantic] [--limit N]
    """
    console = Console()
    cfg: MatrixCLIConfig = ctx.obj  # set by __main__.py
    client = _make_client(cfg)

    try:
        resp = client.search(
            q=q,
            type=type,
            capabilities=_csv_or_none(capabilities),
            frameworks=_csv_or_none(frameworks),
            providers=_csv_or_none(providers),
            mode=mode,
            limit=limit,
            offset=offset,
        )
        if json_out:
            console.print(JSON.from_data(resp))  # pydantic models are json‑able
            raise typer.Exit(0)

        items = resp["items"] if isinstance(resp, dict) else resp.items
        total = resp["total"] if isinstance(resp, dict) else resp.total

        table = Table(title=f"Search results  (total={total})")
        table.add_column("#", justify="right", style="bold")
        table.add_column("Score", justify="right")
        table.add_column("ID", overflow="fold")
        table.add_column("Name", style="bold")
        table.add_column("Ver")
        table.add_column("Type")
        table.add_column("Caps", overflow="fold")
        table.add_column("Frameworks", overflow="fold")
        table.add_column("Providers", overflow="fold")
        table.add_column("Summary", overflow="fold")

        for idx, it in enumerate(items, start=1):
            row = it if isinstance(it, dict) else it.model_dump()
            table.add_row(
                str(idx),
                f"{row.get('score_final', 0):.3f}",
                row.get("id", ""),
                row.get("name", ""),
                row.get("version", ""),
                row.get("type", ""),
                ",".join(row.get("capabilities", []) or []),
                ",".join(row.get("frameworks", []) or []),
                ",".join(row.get("providers", []) or []),
                row.get("summary", "") or "",
            )
        console.print(table)

    except MatrixAPIError as e:
        console.print(f"[red]API error ({e.status_code}):[/] {e.body or e}", highlight=False)
        raise typer.Exit(1)
    except Exception as e:  # pragma: no cover - defensive
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
