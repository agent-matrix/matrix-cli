# matrix_cli/ui/cli.py

import click
from click.core import Context
import sys
import os
import pkgutil
import importlib

from rich.console import Console
from rich.table import Table
from .theme import load_banner, matrix_rain
import click_repl
from click_repl.exceptions import ExitReplException  # <— catch the REPL’s own exit
from click.exceptions import Abort                  # <— catch Click aborts

# Monkey-patch click.Context.protected_args for click_repl compatibility
Context.protected_args = Context.protected_args.setter(
    lambda self, v: setattr(self, "_protected_args", v)
)

console = Console()

@click.group(
    name="matrix",
    invoke_without_command=True,
    help="Film-inspired Matrix Shell for matrix-cli."
)
@click.version_option(version="1.0.0", prog_name="matrix")
@click.option(
    "--rain/--no-rain",
    default=True,
    help="Show Matrix rain animation on startup."
)
@click.option(
    "--no-repl",
    is_flag=True,
    help="Skip the interactive REPL shell after startup."
)
@click.pass_context
def main(ctx: Context, rain: bool, no_repl: bool):
    console.clear()
    if rain:
        # will now last exactly 2 seconds
        matrix_rain(duration=2)

    console.clear()
    console.print(load_banner(), justify="center")
    console.print("[bold green]Welcome to the Matrix Shell![/]\n", justify="center")

    if ctx.invoked_subcommand is None:
        console.print(
            "[dim]Type[/dim] [bold]help[/bold] [dim]to list commands,[/] "
            "[bold]help <command>[/] [dim]for details,[/] "
            "or [bold]--help[/] [dim]for options.[/dim]\n"
        )

    if not no_repl:
        try:
            click_repl.repl(ctx)
        except (KeyboardInterrupt, EOFError, ExitReplException, Abort):
            console.print("\n[bold red]Exiting Matrix Shell...[/]")
            sys.exit(0)


@main.command("help", help="Show help for commands.")
@click.argument("command", required=False)
@click.pass_context
def help_cmd(ctx: Context, command: str):
    if command:
        cmd = main.get_command(ctx, command)
        if cmd:
            click.echo(cmd.get_help(ctx))
        else:
            console.print(f"[red]Error:[/] No such command '{command}'")
    else:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        for name, cmd in main.commands.items():
            table.add_row(name, cmd.short_help or "")
        console.print(table)


@main.command("exit", help="Exit the Matrix Shell.")
@click.pass_context
def exit_cmd(ctx: Context):
    console.print("[bold red]Exiting Matrix Shell...[/]")
    ctx.exit()


# Aliases for convenience
main.add_command(exit_cmd, name="close")
main.add_command(exit_cmd, name="quit")


def _register_commands():
    """
    Auto-discover any click.Command objects in matrix_cli.commands modules
    and register them under our main group.
    """
    pkg_root = __package__.rsplit(".", 1)[0]
    commands_pkg = f"{pkg_root}.commands"
    commands_path = os.path.join(
        os.path.dirname(__file__), "..", "commands"
    )

    for _, module_name, _ in pkgutil.iter_modules([commands_path]):
        try:
            module = importlib.import_module(f"{commands_pkg}.{module_name}")
        except ImportError:
            continue
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, click.core.Command):
                main.add_command(obj)
                break  # register only the first Command per module

_register_commands()

if __name__ == "__main__":
    main()
