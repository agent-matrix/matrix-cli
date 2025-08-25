# matrix_cli/util/tables.py
from __future__ import annotations
from rich.table import Table


def ps_table() -> Table:
    t = Table(show_header=True, header_style="bold")
    t.add_column("ALIAS", style="cyan", no_wrap=True)
    t.add_column("PID", justify="right", no_wrap=True)
    t.add_column("PORT", justify="right", no_wrap=True)
    t.add_column("UPTIME", style="magenta", no_wrap=True)
    t.add_column("URL", style="green")  # <-- NEW
    t.add_column("TARGET")  # keep last so wide paths can wrap
    return t
