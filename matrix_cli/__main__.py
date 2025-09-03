# matrix_cli/__main__.py
from __future__ import annotations
import sys
import typer

# ---- OPTIMIZED FAST PATHS ----
# Handle `matrix --version` and `matrix -V` without importing the full CLI
if len(sys.argv) == 2 and sys.argv[1] in {"--version", "-V"}:
    try:
        from importlib.metadata import version as _v

        print(_v("matrix-cli"))
    except Exception:
        print("0+unknown")
    raise SystemExit(0)

# Handle `matrix version ...` by only loading the version command
if len(sys.argv) > 1 and sys.argv[1] == "version":
    try:
        from matrix_cli.commands.version import app as version_app

        version_app(args=sys.argv[2:], prog_name="matrix version")
    except Exception as e:
        print(f"Error loading version command: {e}", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)

# ---- NEW LAZY COMMAND FAST PATHS (additive, zero startup overhead) ----
# These paths import only the selected command module and execute it directly.
# They keep global startup minimal while enabling the new UX commands.
if len(sys.argv) > 1 and sys.argv[1] in {"do", "help", "chat"}:
    cmd = sys.argv[1]
    try:
        if cmd == "do":
            # Prefer module app to preserve its own option parsing & help.
            from matrix_cli.commands.do import app as do_app  # lazy import
            do_app(args=sys.argv[2:], prog_name="matrix do")
        elif cmd == "help":
            from matrix_cli.commands.help import app as help_app  # lazy import
            help_app(args=sys.argv[2:], prog_name="matrix help")
        else:  # cmd == "chat"
            # chat is optional/beta; import only if present
            try:
                from matrix_cli.commands.chat import app as chat_app  # lazy import
            except Exception:
                print("Chat is not available in this build.", file=sys.stderr)
                raise SystemExit(2)
            chat_app(args=sys.argv[2:], prog_name="matrix chat")
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error loading '{cmd}' command: {e}", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)

# ---- STANDARD COMMAND REGISTRATION ----
from .commands import (
    alias as cmd_alias,
    doctor as cmd_doctor,
    handle_url as cmd_handle_url,
    install as cmd_install,
    link as cmd_link,
    logs as cmd_logs,
    ps as cmd_ps,
    remotes as cmd_remotes,
    run as cmd_run,
    search as cmd_search,
    show as cmd_show,
    stop as cmd_stop,
    version as cmd_version,
    # command groups
    connection as cmd_connection,
    mcp as cmd_mcp,
    uninstall as cmd_uninstall,
)

app = typer.Typer(
    help="Matrix CLI — A thin UX layer over the matrix-python-sdk.",
    no_args_is_help=True,
    add_completion=False,  # Minor optimization for faster startup
)

# Core workflow commands (bind functions directly for clean parsing)
app.command("install")(cmd_install.main)
app.command("run")(cmd_run.main)
app.command("ps")(cmd_ps.main)
app.command("logs")(cmd_logs.main)
app.command("stop")(cmd_stop.main)
app.command("doctor")(cmd_doctor.main)
app.command("search")(cmd_search.main)
app.command("show")(cmd_show.main)
app.command("uninstall")(cmd_uninstall.main)

# Command groups (sub-commands)
app.add_typer(cmd_alias.app, name="alias", help="Manage local component aliases.")
app.add_typer(cmd_link.app, name="link", help="Link a local folder as an alias.")
app.add_typer(cmd_remotes.app, name="remotes", help="Manage Hub remote catalogs.")
app.add_typer(cmd_version.app, name="version", help="Show CLI and SDK versions.")
app.add_typer(
    cmd_connection.app,
    name="connection",
    help="Check connectivity and health of the Matrix Hub.",
)
app.add_typer(
    cmd_mcp.app,
    name="mcp",
    help="MCP utilities (probe an MCP server).",
)

# Hidden internal commands
app.add_typer(
    cmd_handle_url.app,
    name="handle-url",
    help="[Internal] Handle matrix:// deep links.",
    hidden=True,
)

def main() -> None:
    """The main entry point for the CLI application."""
    app()

if __name__ == "__main__":
    main()
