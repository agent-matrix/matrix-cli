# matrix_cli/commands/show.py
from __future__ import annotations

import json
import datetime as _dt
from typing import Any

import typer

from ..config import load_config, client_from_config

app = typer.Typer(help="Show entity details from the Hub")


def _default_json(x: Any):
    # Make datetimes and dates JSON-friendly; fallback to string
    if isinstance(x, (_dt.datetime, _dt.date)):
        return x.isoformat()
    try:
        return str(x)
    except Exception:
        return None


def _to_pretty_json(obj: Any) -> str:
    """
    Robustly turn SDK objects (Pydantic v2/v1 or other) into pretty JSON.
    Tries:
      - model_dump_json(indent=2)
      - model_dump(mode="json") → json.dumps(...)
      - dict() → json.dumps(...)
      - json.dumps(obj, default=_default_json)
      - str(obj) as absolute last resort
    """
    # Pydantic v2: best path
    dump_json = getattr(obj, "model_dump_json", None)
    if callable(dump_json):
        try:
            return dump_json(indent=2)  # pydantic v2 supports indent
        except TypeError:
            # Some versions may not accept indent
            return dump_json()

    # Pydantic v2 or v1: dump to a dict-like structure
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            data = dump(mode="json")  # v2 JSON-friendly types (dates → isoformat)
        except Exception:
            # Fallback: maybe v2/v1 without mode kw
            try:
                data = dump()
            except Exception:
                data = None
        if data is not None:
            return json.dumps(data, indent=2, sort_keys=False, default=_default_json)

    # Pydantic v1: .dict()
    as_dict = getattr(obj, "dict", None)
    if callable(as_dict):
        try:
            data = as_dict()
            return json.dumps(data, indent=2, sort_keys=False, default=_default_json)
        except Exception:
            pass

    # Try dumping with a default encoder
    try:
        return json.dumps(obj, indent=2, sort_keys=False, default=_default_json)
    except TypeError:
        # Last resort
        return json.dumps(str(obj), indent=2)


@app.command()
def main(id: str = typer.Argument(..., help="Fully-qualified ID of the entity")):
    """
    Show a Hub entity as pretty JSON.
    """
    client = client_from_config(load_config())
    ent = client.entity(id)
    typer.echo(_to_pretty_json(ent))
