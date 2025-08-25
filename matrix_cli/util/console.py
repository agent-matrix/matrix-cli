from __future__ import annotations
from rich.console import Console

console = Console(highlight=False)


def info(msg: str) -> None:
    console.print(f"[bold cyan]»[/] {msg}")


def success(msg: str) -> None:
    console.print(f"[bold green]✓[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"[bold yellow]![/] {msg}")


def error(msg: str) -> None:
    console.print(f"[bold red]✗[/] {msg}")
