import click
from rich.console import Console
from .theme import load_banner, matrix_rain
from click_repl import repl

console = Console()

@click.command()
@click.option("--rain/--no-rain", default=True, help="Show Matrix rain on startup.")
@click.option("--no-repl", is_flag=True, help="Skip interactive shell.")
def main(rain: bool, no_repl: bool):
    """Film‑inspired Matrix shell for matrix-cli."""
    console.clear()
    if rain:
        matrix_rain(duration=4)
    console.clear()
    console.print(load_banner(), justify="center")
    console.print("[bold green]Welcome to the Matrix Shell![/]\n", justify="center")

    if not no_repl:
        console.print(
            "Type core commands (e.g. 'search', 'install') exactly as you would with `matrix ...`."
        )
        repl(click.get_current_context())