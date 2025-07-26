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

app = typer.Typer(help="Install an entity into a target project.")


def _make_client(cfg: MatrixCLIConfig) -> MatrixClient:
    cache = Cache(cache_dir=cfg.cache_dir, ttl=cfg.cache_ttl)
    return MatrixClient(cfg.registry_url, token=cfg.registry_token, cache=cache)


@app.command("run")
def install_cmd(
    ctx: typer.Context,
    id: str = typer.Argument(..., help="Entity UID or short id (type:name)"),
    target: str = typer.Option(..., "--target", "-t", help="Project directory"),
    version: Optional[str] = typer.Option(None, "--version", "-v", help="Version if id is short"),
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSON"),
) -> None:
    """
    matrix install agent:pdf-summarizer@1.4.2 --target ./apps/pdf-bot
    """
    console = Console()
    cfg: MatrixCLIConfig = ctx.obj
    client = _make_client(cfg)

    try:
        res = client.install(id=id, target=target, version=version)
        if json_out:
            console.print(JSON.from_data(res))
            raise typer.Exit(0)

        data = res if isinstance(res, dict) else res.model_dump()

        # Steps
        steps = data.get("results", [])
        st = Table(title="Install steps")
        st.add_column("#", justify="right")
        st.add_column("Step")
        st.add_column("OK")
        st.add_column("Elapsed (s)", justify="right")
        st.add_column("Notes", overflow="fold")
        for i, s in enumerate(steps, start=1):
            ok = "✅" if s.get("ok") else "❌"
            note = s.get("stderr") or s.get("stdout") or ""
            st.add_row(str(i), s.get("step", ""), ok, f"{s.get('elapsed_secs', 0):.2f}", note[:160])
        console.print(st)

        # Files
        files = data.get("files_written", []) or []
        if files:
            ft = Table(title="Files written")
            ft.add_column("Path", overflow="fold")
            for p in files:
                ft.add_row(str(p))
            console.print(ft)

        # Lockfile hint
        lock = data.get("lockfile", {}) or {}
        if lock:
            console.print("Lockfile written (matrix.lock.json).")

    except MatrixAPIError as e:
        console.print(f"[red]API error ({e.status_code}):[/] {e.body or e}", highlight=False)
        raise typer.Exit(1)
    except Exception as e:  # pragma: no cover
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
