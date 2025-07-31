# matrix_cli/ui/theme.py

import time
import random
from rich.text import Text
from rich.panel import Panel
from rich.console import Console
import shutil
import os

# Path to the ASCII banner asset
BANNER_PATH = os.path.join(os.path.dirname(__file__), "assets", "banner.txt")


def load_banner() -> Panel:
    """
    Reads the ASCII art banner from disk and wraps it in a Rich Panel.
    Falls back to a simple title if the file is missing or empty.
    """
    try:
        with open(BANNER_PATH, encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            raise ValueError("Empty banner file")
    except Exception:
        raw = "╔═╗┌─┐┌─┐┌─┐┌─┐┌┬┐   Matrix Shell"
    text = Text(raw, style="bold green")
    return Panel(text, border_style="green", padding=(1, 2))


def matrix_rain(lines: int = None, width: int = None, duration: float = 1.0):
    """
    Displays a Matrix-style rain animation in the terminal.

    Args:
      lines:  Number of rows (defaults to terminal height - 2)
      width:  Number of columns (defaults to terminal width - 2)
      duration: How long to run the animation, in seconds.
    """
    console = Console()
    size = console.size
    rows = lines or max(1, size.height - 2)
    cols = width or max(1, size.width - 2)

    chars = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*()[]{}<>")
    end_time = time.time() + duration

    while time.time() < end_time:
        frame = "\n".join(
            "".join(random.choice(chars) for _ in range(cols)) for _ in range(rows)
        )
        console.clear()
        console.print(Text(frame, style="green"))
        time.sleep(0.05)


__all__ = ["load_banner", "matrix_rain"]
