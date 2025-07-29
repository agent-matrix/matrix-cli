import time
import random
from rich.text import Text
from rich.panel import Panel
import pkg_resources
from rich.console import Console

# Load ASCII banner
raw_bytes = pkg_resources.resource_stream(
    __name__, "assets/banner.txt"
).read()


def load_banner() -> Panel:
    raw = raw_bytes.decode("utf-8")
    return Panel(Text(raw, style="bold green"), border_style="green")


def matrix_rain(lines=15, width=60, duration=3):
    console = Console()
    rain_chars = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*()[]{}<>")
    start = time.time()
    while time.time() - start < duration:
        frame = "\n".join(
            "".join(random.choice(rain_chars) for _ in range(width))
            for _ in range(lines)
        )
        console.clear()
        console.print(frame, style="green")
        time.sleep(0.05)