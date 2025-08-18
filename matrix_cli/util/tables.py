from __future__ import annotations
from rich.table import Table

def ps_table():
    t = Table(show_header=True, header_style="bold magenta")
    t.add_column("ALIAS", style="bold cyan")
    t.add_column("PID", justify="right")
    t.add_column("PORT", justify="right")
    t.add_column("UPTIME")
    t.add_column("TARGET")
    return t
