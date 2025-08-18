from __future__ import annotations
import json
import typer
from ..config import load_config, client_from_config

app = typer.Typer(help="Show entity details from the Hub")

@app.command()
def main(id: str = typer.Argument(..., help="Fully-qualified ID of the entity")):
    client = client_from_config(load_config())
    ent = client.entity(id)
    print(json.dumps(ent, indent=2))
