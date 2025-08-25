from __future__ import annotations
import typer
from urllib.parse import urlsplit, parse_qs

from ..config import load_config, client_from_config, target_for
from ..util.console import success, error, info

app = typer.Typer(help="Handle matrix:// deep links (install)")


@app.command("install")
def main(url: str = typer.Argument(..., help="Full matrix:// URL from the OS")):
    """
    Example:
    matrix handle-url install 'matrix://install?id=mcp_server%3Ahello-sse-server%400.1.0&alias=hello-sse'
    """
    try:
        from matrix_sdk.deep_link import parse as parse_dl
        from matrix_sdk.installer import LocalInstaller
        from matrix_sdk.alias import AliasStore
        from matrix_sdk.ids import suggest_alias
    except Exception as e:  # pragma: no cover
        error(f"SDK not installed correctly: {e}")
        raise typer.Exit(1)

    # parse hub override (?hub=)
    hub_override: str | None = None
    try:
        u = urlsplit(url)
        qs = parse_qs(u.query)
        hub_override = (qs.get("hub") or [None])[0]
        dl = parse_dl(url)
    except Exception as e:
        error(f"Invalid deep link: {e}")
        raise typer.Exit(2)

    cfg = load_config()
    if hub_override:
        cfg = type(cfg)(hub_base=hub_override, token=cfg.token, home=cfg.home)

    client = client_from_config(cfg)
    installer = LocalInstaller(client)
    alias = dl.alias or suggest_alias(dl.id)
    target = target_for(dl.id, alias=alias, cfg=cfg)

    info(f"Installing {dl.id} → {target}")
    try:
        installer.build(dl.id, target=target, alias=alias)
    except Exception as e:
        error(f"Install failed: {e}")
        raise typer.Exit(10)

    # Save alias
    try:
        AliasStore().set(alias, id=dl.id, target=target)
    except Exception as e:
        error(f"Installed, but failed to save alias: {e}")
        raise typer.Exit(1)

    success(f"installed {dl.id}")
    info(f"→ {target}")
    info(f"Next: matrix run {alias}")
