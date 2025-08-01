# matrix_cli/ui/cli.py

import click
from click.core import Context
import sys
import os
import pkgutil
import importlib

from rich.console import Console
from .theme import load_banner, matrix_rain
import click_repl
from click_repl.exceptions import ExitReplException
from click_repl import utils as repl_utils
from click.exceptions import Abort

console = Console()

# --- Treat a leading group token (e.g., 'matrix') as redundant ----------------
# If the first token equals the group's name, drop it before Click resolves the
# command. This makes entering `matrix` or `matrix <subcmd>` behave like just
# `<subcmd>` inside the REPL, avoiding "No such command 'matrix'".
from click.core import Group as _ClickGroup
_original_group_resolve = _ClickGroup.resolve_command

def _patched_group_resolve(self, ctx, args):
    # If first token matches the group's name *and* there is NO real subcommand
    # named the same, treat it as redundant (REPL users often type `matrix`).
    if args and isinstance(args[0], str):
        first = args[0]
        if first == getattr(self, 'name', '') and self.get_command(ctx, first) is None:
            args = args[1:]
    return _original_group_resolve(self, ctx, args)

_ClickGroup.resolve_command = _patched_group_resolve
# -----------------------------------------------------------------------------

# --- Workaround for typing 'matrix ' crashing completions --------------------
# Some versions of click-repl try to resolve the first token as a subcommand.
# When the token equals the *group name* ("matrix"), resolution can fail during
# async completion after a trailing space. We defensively drop the leading
# program/group name so completion works (Tab still provides suggestions).
_original_resolve_context = repl_utils._resolve_context

def _safe_resolve_context(args, ctx):
    # If the first token is exactly the current group's program name and there
    # is no subcommand with that name, ignore it to keep the completer happy.
    if args and isinstance(args[0], str):
        first = args[0]
        try:
            has_real_cmd = ctx.command.get_command(ctx, first) is not None
        except Exception:
            has_real_cmd = False
        if first == getattr(ctx.command, 'name', '') and not has_real_cmd:
            args = args[1:]
    return _original_resolve_context(args, ctx)

repl_utils._resolve_context = _safe_resolve_context
# -----------------------------------------------------------------------------

# Monkey-patch click.Context.protected_args for click_repl compatibility
# Provide both getter and setter to avoid AttributeError when click_repl sets protected_args
def _get_protected_args(self):
    return getattr(self, '_protected_args', tuple(self.args))

def _set_protected_args(self, value):
    setattr(self, '_protected_args', value)

Context.protected_args = property(_get_protected_args, _set_protected_args)

@click.group(
    name="matrix",
    invoke_without_command=True,
    help="Film-inspired Matrix Shell for matrix-cli."
)
@click.version_option(version="1.0.0", prog_name="matrix")
@click.option('--rain/--no-rain', default=True, help='Show Matrix rain animation on startup.')
@click.option('--no-repl', is_flag=True, default=False, help='Exit after executing command and do not enter REPL.')
@click.pass_context
def main(ctx: Context, rain: bool, no_repl: bool):
    """Matrix CLI Shell."""
    # Initial clear and optional rain animation
    console.clear()
    if rain:
        matrix_rain(duration=2)

    # Clear again, then show banner and welcome
    console.clear()
    banner = load_banner()
    if banner:
        console.print(banner, justify="center")
    console.print("[bold green]Matrix Shell v0.1.0[/]\n", justify="center")

    # Show usage hint when no subcommand given
    if ctx.invoked_subcommand is None:
        console.print(
            "[dim]Type[/dim] [bold]help[/bold] [dim]to list commands,[/] "
            "[bold]help <command>[/] [dim]for details,[/] "
            "[bold]--help[/] [dim]for options.[/dim]\n",
            justify="center"
        )

    # If a command was invoked directly, let click handle it
    if ctx.invoked_subcommand:
        return

    # If --no-repl was specified, show help and exit
    if no_repl:
        click.echo(main.get_help(ctx))
        sys.exit(0)

    # Otherwise, enter interactive REPL with typing-based completion disabled
    try:
        # Disable complete while typing to avoid errors on space input
        click_repl.repl(ctx, prompt_kwargs={'complete_while_typing': False})
    except (KeyboardInterrupt, EOFError, ExitReplException, Abort):
        console.print("\n[bold red]Exiting Matrix Shell...[/]")
        sys.exit(0)

@main.command('help', help='Show help for commands.')
@click.argument('command', required=False)
@click.pass_context
def help_cmd(ctx: Context, command: str):
    """
    With no arguments, print top-level help (usage, options, all commands).
    With a subcommand name, print that command’s help.
    """
    if command:
        cmd = main.get_command(ctx, command)
        if cmd:
            click.echo(cmd.get_help(ctx))
        else:
            console.print(f"[red]Error:[/] No such command '{command}'")
    else:
        click.echo(main.get_help(ctx))

# Alias 'matrix' to reprint help (Click-level)
main.add_command(help_cmd, name="matrix")


@main.command('exit', help='Exit the Matrix Shell.')
@click.pass_context
def exit_cmd(ctx: Context):
    # Print a message and raise ExitReplException to break out of click-repl's loop
    console.print('[bold red]Exiting Matrix Shell...[/]')
    raise ExitReplException()

# Additional exit aliases
main.add_command(exit_cmd, name='quit')
main.add_command(exit_cmd, name='close')

@main.command('clear', help='Clear the Matrix Shell screen.')
def clear_cmd():
    console.clear()

# Auto-discover commands from matrix_cli.commands

def _register_commands():
    commands_pkg = 'matrix_cli.commands'
    commands_path = os.path.join(os.path.dirname(__file__), '..', 'commands')
    for _, module_name, _ in pkgutil.iter_modules([commands_path]):
        try:
            module = importlib.import_module(f"{commands_pkg}.{module_name}")
        except ImportError:
            continue
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, click.core.Command):
                main.add_command(obj)
                break

_register_commands()

if __name__ == '__main__':
    main()
