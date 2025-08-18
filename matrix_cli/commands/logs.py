# matrix_cli/commands/logs.py
from __future__ import annotations
import typer

from ..util.console import error

app = typer.Typer(help="Tail logs for an alias")


@app.command()
def main(
    alias: str,
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(40, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """
    Tail logs for an alias.

    Notes:
      • Do NOT test an iterator's truthiness — some custom iterables get consumed.
      • Treat only `None` as "no logs".
    """
    from matrix_sdk import runtime

    try:
        it = runtime.tail_logs(alias, follow=follow, n=lines)

        # Only treat None as "no logs".
        if it is None:
            error(f"No log file found for alias '{alias}'.")
            raise typer.Exit(1)

        emitted = 0
        for line in it:
            # Normalize to str safely
            if isinstance(line, bytes):
                text = line.decode("utf-8", "replace")
            else:
                text = str(line)

            # Use Click/Typer writer (capture-safe)
            # Keep original line endings intact; most tailers yield with '\n'
            typer.echo(text, nl=False)
            emitted += 1

        # Success path (even if file had 0 lines)
        return

    except KeyboardInterrupt:
        # Graceful stop in follow mode
        return
    except Exception as e:
        error(f"Failed to tail logs: {e}")
        raise typer.Exit(1)
