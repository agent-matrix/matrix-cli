# matrix_cli/ui/cli.py

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
import threading
from typing import Optional

import click
from click.core import Context
from click.exceptions import Abort
from rich.console import Console

import click_repl
from click_repl import utils as repl_utils
from click_repl.exceptions import ExitReplException

from .theme import load_banner, matrix_rain

# Session state
RAIN_ENABLED: bool = True
REPL_ACTIVE: bool = False

console = Console()

# Optional Typer → Click bridge (for auto-discovery)
try:  # pragma: no cover
    import typer  # type: ignore
    from typer.main import get_command as _typer_get_command  # type: ignore
except Exception:  # pragma: no cover
    typer = None  # type: ignore
    _typer_get_command = None  # type: ignore

# ---- Make leading "matrix" token optional and options-first safe -------------
from click.core import Group as _ClickGroup  # noqa: E402
_original_group_resolve = _ClickGroup.resolve_command


def _patched_group_resolve(self, ctx, args):
    if args and isinstance(args[0], str):
        first = args[0]
        try:
            has_real_cmd = self.get_command(ctx, first) is not None
        except Exception:
            has_real_cmd = False

        if first == getattr(self, "name", ""):
            if len(args) > 1 and isinstance(args[1], str) and args[1].startswith("-"):
                args = args[1:]
            elif not has_real_cmd:
                args = args[1:]

    if args and isinstance(args[0], str) and args[0].startswith("-"):
        return (getattr(self, "name", None), self, args)

    if not args:
        cmd = self.get_command(ctx, "matrix") or self.get_command(ctx, "help")
        if cmd is not None:
            return (cmd.name, cmd, [])
        return (None, None, [])

    return _original_group_resolve(self, ctx, args)


_ClickGroup.resolve_command = _patched_group_resolve

# ---- Keep completer stable when typing "matrix " or options first ------------
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
    return _original_resolve_context(args, ctx)


repl_utils._resolve_context = _safe_resolve_context

# ---- click_repl compatibility: add setter for protected_args -----------------
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
    global RAIN_ENABLED
    RAIN_ENABLED = bool(rain)

    # If a subcommand (help/exit/clear/screensaver) was resolved, let Click run it.
    if ctx.invoked_subcommand:
        return

    # Inside REPL with only group options (e.g., --no-rain): apply and return.
    if REPL_ACTIVE:
        console.print(
            f"[dim]Matrix rain is now {'enabled' if RAIN_ENABLED else 'disabled'}.[/]"
        )
        return

    # One-shot non-REPL path
    if no_repl:
        tmp_ctx = click.Context(main, info_name="matrix", obj=ctx.obj)
        click.echo(main.get_help(tmp_ctx))
        sys.exit(0)

    # Startup UX
    console.clear()
    if RAIN_ENABLED:
        matrix_rain(duration=2)

    console.clear()
    banner = load_banner()
    if banner:
        console.print(banner, justify="center")
    console.print("[bold green]Matrix Shell v0.1.0[/]\n", justify="center")

    console.print(
        "[dim]Type[/dim] [bold]help[/bold] [dim]to list commands,[/] "
        "[bold]help <command>[/] [dim]for details,[/] "
        "[bold]--help[/] [dim]for options.[/dim]\n",
        justify="center",
    )

    _run_repl(ctx)


def _run_repl(parent_ctx: Context) -> None:
    global REPL_ACTIVE
    group_ctx = click.Context(parent_ctx.command, info_name="matrix", obj=parent_ctx.obj)
    group_ctx.args = []
    try:
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
    tmp_ctx = click.Context(main, info_name="matrix", obj=ctx.obj)
    if command:
        cmd = main.get_command(tmp_ctx, command)
        if cmd:
            click.echo(cmd.get_help(tmp_ctx))
        else:
            console.print(f"[red]Error:[/] No such command '{command}'")
    else:
        click.echo(main.get_help(tmp_ctx))


# Also expose top-level name as a command for convenience in REPL
main.add_command(help_cmd, name="matrix")


@main.command("exit", help="Exit the Matrix Shell.")
@click.pass_context
def exit_cmd(ctx: Context) -> None:
    console.print("[bold red]Exiting Matrix Shell...[/]")
    raise ExitReplException()


main.add_command(exit_cmd, name="quit")
main.add_command(exit_cmd, name="close")


@main.command("clear", help="Clear the Matrix Shell screen.")
def clear_cmd() -> None:
    console.clear()


# Screensaver: use the same animation from theme.py, loop until keypress
@main.command("screensaver", help="Start Matrix rain; press any key to return.")
def screensaver_cmd() -> None:
    stop = threading.Event()

    def _wait_keypress():
        try:
            click.getchar()
        except Exception:
            pass
        finally:
            stop.set()

    t = threading.Thread(target=_wait_keypress, daemon=True)
    t.start()
    try:
        console.clear()
        console.print("[dim]Screensaver running — press any key to return...[/]")
        # Run the same animation repeatedly in short slices until a key is pressed.
        while not stop.is_set():
            matrix_rain(duration=1.5, fps=30)
    finally:
        stop.set()
        t.join()
        console.clear()


# ----------------------- Auto-discover Typer/Click commands -------------------
def _register_commands() -> None:
    commands_pkg = "matrix_cli.commands"
    commands_path = os.path.join(os.path.dirname(__file__), "..", "commands")

    for _, module_name, _ in pkgutil.iter_modules([commands_path]):
        try:
            module = importlib.import_module(f"{commands_pkg}.{module_name}")
        except Exception:
            continue

        app_obj = getattr(module, "app", None)
        if typer and _typer_get_command and isinstance(app_obj, typer.Typer):
            try:
                click_cmd = _typer_get_command(app_obj)
                main.add_command(click_cmd, name=module_name)
                continue
            except Exception:
                pass

        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, click.core.Command):
                main.add_command(obj)
                break


_register_commands()

# -----------------------------------------------------------------------------


if __name__ == "__main__":
    main()
