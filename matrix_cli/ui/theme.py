# matrix_cli/ui/theme.py

import os
import time
import random
from shutil import get_terminal_size
from rich.console import Console

console = Console()

def load_banner() -> str:
    """
    Load and return the ASCII banner from assets/banner.txt.
    """
    banner_path = os.path.join(
        os.path.dirname(__file__),
        "assets",
        "banner.txt"
    )
    try:
        with open(banner_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "[bold red]Matrix Banner Not Found[/]"

def matrix_rain(duration: float = 2.0, fps: int = 30):
    """
    Show a Matrix-style rain animation for `duration` seconds.
    `fps` controls the frame rate.
    """
    width, height = get_terminal_size()
    columns = [0] * width
    start = time.time()
    interval = 1.0 / fps

    while time.time() - start < duration:
        line = []
        for i in range(width):
            # Randomly start a drop if none exists
            if columns[i] == 0 and random.random() < 0.005:
                columns[i] = 1
            if columns[i] > 0:
                # “Head” of the drop
                char = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
                line.append(f"[bright_green]{char}[/]")
                columns[i] += 1
                # Drop resets when it exceeds the screen or randomly
                if columns[i] > height or random.random() < 0.02:
                    columns[i] = 0
            else:
                line.append(" ")
        console.print("".join(line), end="\r")
        time.sleep(interval)

    # Clear screen when done
    console.clear()
