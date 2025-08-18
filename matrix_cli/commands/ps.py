from __future__ import annotations
import time
import typer

from ..util.console import info
from ..util.tables import ps_table

app = typer.Typer(help="List running servers")

@app.command()
def main():
    from matrix_sdk import runtime
    from rich.console import Console

    rows = runtime.status()
    table = ps_table()
    now = time.time()
    for r in sorted(rows, key=lambda x: x.alias):
        up = int(now - float(r.started_at))
        h, rem = divmod(up, 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h:02d}:{m:02d}:{s:02d}"
        table.add_row(r.alias, str(r.pid), str(r.port or "-"), uptime_str, r.target)

    Console().print(table)
    info(f"{len(rows)} running process(es).")
