# matrix_cli/ui/cli.py

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from typing import Optional

import click
from click.core import Context
from click.exceptions import Abort
from rich.console import Console

import click_repl
from click_repl import utils as repl_utils
from click_repl.exceptions import ExitReplException

from .theme import load_banner, matrix_rain

# -----------------------------------------------------------------------------
# Session state (in-memory)
# -----------------------------------------------------------------------------
# Whether the Matrix "rain" animation is enabled for this process/session.
# This is updated when the group is invoked with --rain/--no-rain,
# including inside the REPL via "matrix --no-rain".
RAIN_ENABLED: bool = True

# True while we are inside the click-repl loop.
REPL_ACTIVE: bool = False

console = Console()

# Optional (for auto-register): convert Typer sub-apps to Click
try:  # pragma: no cover - optional dependency handling
    import typer  # type: ignore
    from typer.main import get_command as _typer_get_command  # type: ignore
except Exception:  # pragma: no cover
    typer = None  # type: ignore
    _typer_get_command = None  # type: ignore

# --- Treat a leading group token (e.g., 'matrix') as redundant ----------------
# If the first token equals the group's name AND there is no real subcommand
# named 'matrix', drop it before Click resolves the command. This allows users
# to type `matrix` or `matrix <subcmd>` in the REPL. When args end up empty,
# return the help command so Click won't call the group's callback (which would
# expect options like --rain/--no-repl).
from click.core import Group as _ClickGroup  # noqa: E402

_original_group_resolve = _ClickGroup.resolve_command


def _patched_group_resolve(self, ctx, args):
    """
    Safer resolver for REPL usage.

    Goals:
    - Allow typing a redundant leading 'matrix'.
    - If the next token is an option (starts with '-'), make the GROUP handle it
      by returning the group itself, so Click parses group options (e.g. --version,
      --no-rain) instead of trying to resolve a subcommand. This avoids the
      'cmd is None' assertion inside click.repl's initial invoke.
    - Preserve the ability to run the real 'matrix' subcommand we register (help alias).
    """
    # 1) Handle redundant leading 'matrix'
    if args and isinstance(args[0], str):
        first = args[0]
        try:
            has_real_cmd = self.get_command(ctx, first) is not None
        except Exception:
            has_real_cmd = False

        if first == getattr(self, "name", ""):
            # If followed by an option, we are dealing with group-level options:
            # drop the leading group token so Click parses the options on the group.
            if len(args) > 1 and isinstance(args[1], str) and args[1].startswith("-"):
                args = args[1:]
            # Or, if there is no real 'matrix' subcommand, drop the redundant token.
            elif not has_real_cmd:
                args = args[1:]

    # 2) If the first remaining token is an option, let the GROUP parse it.
    #    Return the group itself so click.core.Group.invoke() will build a new
    #    context, parse the options (consuming them), and then call our callback.
    if args and isinstance(args[0], str) and args[0].startswith("-"):
        return (getattr(self, "name", None), self, args)

    # 3) No tokens left: prefer our help alias or the built-in help command
    if not args:
        cmd = self.get_command(ctx, "matrix") or self.get_command(ctx, "help")
        if cmd is not None:
            return (cmd.name, cmd, [])
        # Fallback: tell Click there is no command (it will show an error).
        return (None, None, [])

    # 4) Default behavior
    return _original_group_resolve(self, ctx, args)


_ClickGroup.resolve_command = _patched_group_resolve
# -----------------------------------------------------------------------------


# --- Workaround for typing 'matrix ' crashing completions --------------------
# Some click-repl versions choke when the first token equals the group name.
# Drop the leading token in the completer path IFF there is no real subcommand,
# or if the next token is an option (so options can bind to the group).
_original_resolve_context = repl_utils._resolve_context


def _safe_resolve_context(args, ctx):
    if args and isinstance(args[0], str):
        first = args[0]
        try:
            has_real_cmd = ctx.command.get_command(ctx, first) is not None
        except Exception:
            has_real_cmd = False

        if first == getattr(ctx.command, "name", ""):
            if (len(args) > 1 and isinstance(args[1], str) and args[1].startswith("-")) or not has_real_cmd:
                args = args[1:]

    # Delegate to the original resolution (which will now use the patched resolver)
    return _original_resolve_context(args, ctx)


repl_utils._resolve_context = _safe_resolve_context
# -----------------------------------------------------------------------------


# --- click_repl compatibility: protected_args needs a setter in some versions -
def _get_protected_args(self):
    return getattr(self, "_protected_args", tuple(self.args))


def _set_protected_args(self, value):
    setattr(self, "_protected_args", value)


Context.protected_args = property(_get_protected_args, _set_protected_args)
# -----------------------------------------------------------------------------


@click.group(
    name="matrix",
    invoke_without_command=True,
    help="Matrix Shell — explore and run Matrix CLI commands interactively.",
)
@click.version_option(version="0.1.0", prog_name="matrix")
@click.option(
    "--rain/--no-rain",
    default=True,
    help="Show Matrix rain animation on startup.",
)
@click.option(
    "--no-repl",
    is_flag=True,
    default=False,
    help="Exit after executing command and do not enter REPL.",
)
@click.pass_context
def main(ctx: Context, rain: bool = True, no_repl: bool = False) -> None:
    """Matrix CLI Shell.

    Inside the shell:
      • Type `help` or `matrix help` to see commands.
      • Type `help <command>` for detailed usage and options.
      • Type `clear` or `matrix clear` to clear the screen.
      • Type `exit`, `quit`, or `close` (with or without `matrix`) to exit.
    """
    global RAIN_ENABLED

    # Update session rain flag from current invocation (top-level or within REPL).
    RAIN_ENABLED = bool(rain)

    # If a subcommand was invoked (e.g., 'help', 'exit', 'clear' or others), do NOT
    # clear the screen or run the rain animation. Let Click dispatch the subcommand.
    if ctx.invoked_subcommand:
        return

    # If we're being called from inside the REPL *with only options* (like `--no-rain`
    # or `--version`), do not try to start a nested REPL. Just acknowledge and return.
    if REPL_ACTIVE:
        # For --version, Click already handled printing and exiting before reaching here.
        # For --rain/--no-rain, reflect state and return.
        console.print(
            f"[dim]Matrix rain is now {'enabled' if RAIN_ENABLED else 'disabled'}.[/]"
        )
        return

    # We are at top-level (not in REPL) and no subcommand was given.
    # Respect --no-repl by printing help and exiting.
    if no_repl:
        tmp_ctx = click.Context(main, info_name="matrix", obj=ctx.obj)
        click.echo(main.get_help(tmp_ctx))
        sys.exit(0)

    # Normal startup experience (top-level, no subcommand, no --no-repl):
    # Clear and optionally show rain, then banner.
    console.clear()
    if RAIN_ENABLED:
        matrix_rain(duration=2)

    console.clear()
    banner = load_banner()
    if banner:
        console.print(banner, justify="center")
    console.print("[bold green]Matrix Shell v0.1.0[/]\n", justify="center")

    # Show usage hint when no subcommand given
    console.print(
        "[dim]Type[/dim] [bold]help[/bold] [dim]to list commands,[/] "
        "[bold]help <command>[/] [dim]for details,[/] "
        "[bold]--help[/] [dim]for options.[/dim]\n",
        justify="center",
    )

    # Enter interactive REPL; disable complete-while-typing to avoid space-crashes
    _run_repl(ctx)


def _run_repl(parent_ctx: Context) -> None:
    """Enter the interactive REPL loop safely."""
    global REPL_ACTIVE

    # Create a fresh root context for the REPL with a friendly name.
    group_ctx = click.Context(parent_ctx.command, info_name="matrix", obj=parent_ctx.obj)

    # Ensure there are no leftover args before the initial group.invoke().
    # This avoids resolve_command() being called with stray args and asserting.
    group_ctx.args = []
    try:
        # If available (via our property patch), also clear protected args.
        group_ctx.protected_args = ()
    except Exception:
        pass

    try:
        REPL_ACTIVE = True
        click_repl.repl(group_ctx, prompt_kwargs={"complete_while_typing": False})
    except ExitReplException:
        sys.exit(0)
    except (KeyboardInterrupt, EOFError, Abort):
        console.print("\n[bold red]Exiting Matrix Shell...[/]")
        sys.exit(0)
    finally:
        REPL_ACTIVE = False


@main.command("help", help="Show help for commands.")
@click.argument("command", required=False)
@click.pass_context
def help_cmd(ctx: Context, command: Optional[str]) -> None:
    """
    With no arguments, print top-level help (usage, options, all commands).
    With a subcommand name, print that command’s help.
    """
    # IMPORTANT: Do *not* clear the screen or run rain when showing help.
    tmp_ctx = click.Context(main, info_name="matrix", obj=ctx.obj)
    if command:
        cmd = main.get_command(tmp_ctx, command)
        if cmd:
            click.echo(cmd.get_help(tmp_ctx))
        else:
            console.print(f"[red]Error:[/] No such command '{command}'")
    else:
        click.echo(main.get_help(tmp_ctx))


# Let users type `matrix` inside the REPL to view the top-level help.
# Keep as a real Click subcommand so it appears in completions too.
main.add_command(help_cmd, name="matrix")


@main.command("exit", help="Exit the Matrix Shell.")
@click.pass_context
def exit_cmd(ctx: Context) -> None:
    """Exit the interactive Matrix Shell."""
    console.print("[bold red]Exiting Matrix Shell...[/]")
    # Break out of click-repl's loop cleanly
    raise ExitReplException()


# Additional exit aliases (both with and without 'matrix' prefix work)
main.add_command(exit_cmd, name="quit")
main.add_command(exit_cmd, name="close")


@main.command("clear", help="Clear the Matrix Shell screen.")
def clear_cmd() -> None:
    """Clear the terminal screen."""
    console.clear()


# ----------------------- Auto-discover Typer/Click commands -------------------


def _register_commands() -> None:
    """
    Auto-discover commands in matrix_cli.commands and register them.

    Supports:
      • Typer sub-apps (module-level `app = typer.Typer(...)`), converted to
        Click commands via typer.main.get_command and mounted under the module's
        name (e.g., commands/search.py -> `search`).
      • Raw Click commands/groups (first found object per module).
    """
    commands_pkg = "matrix_cli.commands"
    commands_path = os.path.join(os.path.dirname(__file__), "..", "commands")

    for _, module_name, _ in pkgutil.iter_modules([commands_path]):
        try:
            module = importlib.import_module(f"{commands_pkg}.{module_name}")
        except Exception:
            continue

        # Prefer a Typer app named `app` if present
        app_obj = getattr(module, "app", None)
        if typer and _typer_get_command and isinstance(app_obj, typer.Typer):
            try:
                click_cmd = _typer_get_command(app_obj)
                # Mount under the file's module name (search, show, install, list, remotes)
                main.add_command(click_cmd, name=module_name)
                continue
            except Exception:
                # Fall back to raw Click discovery below
                pass

        # Otherwise, register the first Click command/group exported by the module
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, click.core.Command):
                main.add_command(obj)
                break  # only the first Command per module


_register_commands()

# -----------------------------------------------------------------------------


if __name__ == "__main__":
    main()
