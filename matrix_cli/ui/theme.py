# matrix_cli/ui/theme.py

import os
import time
import random
from shutil import get_terminal_size
from rich.console import Console

console = Console()

# Katakana and symbols inspired by The Matrix film
MATRIX_CHARS = (
    "ﾊﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ"  # Common katakana
    "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ"  # Additional katakana
    "0123456789"            # Numerals for variety
)

def load_banner() -> str:
    """
    Load and return the ASCII banner from assets/banner.txt,
    wrapped in bright green for that classic Matrix look.
    """
    banner_path = os.path.join(
        os.path.dirname(__file__),
        "assets",
        "banner.txt"
    )
    try:
        with open(banner_path, encoding="utf-8") as f:
            content = f.read()
            # Wrap in bright green tags to color the entire banner
            return f"[bright_green]{content}[/bright_green]"
    except FileNotFoundError:
        # If banner is missing, show error in bold red
        return "[bold red]Matrix Banner Not Found[/]"

# Helper class to manage the state of each column of falling characters
class Column:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.reset()

    def reset(self):
        """Resets the column to a new random state."""
        self.head = random.randint(0, self.height)
        self.length = random.randint(self.height // 3, self.height - 2)
        self.speed = random.uniform(0.2, 1.5)
        self.frames = 0
        self.finished = False

    def update(self):
        """Moves the column down and checks if it's off-screen."""
        self.frames += 1
        # Move the head of the drop down based on its speed
        if self.frames * self.speed > 1:
            self.head += 1
            self.frames = 0
        
        # If the tail has moved past the bottom of the screen, mark as finished
        if self.head - self.length > self.height:
            self.finished = True


def matrix_rain(duration: float = 4.0, fps: int = 24):
    """
    Show a full-screen Matrix-style rain animation.
    """
    # Hide the cursor for a cleaner look
    console.show_cursor(False)
    
    width, height = get_terminal_size()
    # Create a list of Column objects, one for each column of the terminal
    columns = [Column(width, height) for _ in range(width)]
    
    start = time.time()
    interval = 1.0 / fps

    try:
        while time.time() - start < duration:
            frame = []
            for y in range(height):
                line = []
                for x in range(width):
                    col = columns[x]
                    char = " "
                    style = "black"

                    # The head of the drop is white
                    if y == col.head:
                        style = "white"
                        char = random.choice(MATRIX_CHARS)
                    # The main body of the drop is bright green
                    elif col.head > y > col.head - col.length:
                        style = "bright_green"
                        char = random.choice(MATRIX_CHARS)
                    # The fading tail is a dimmer green
                    elif col.head - col.length <= y <= col.head:
                        style = "green"
                        char = random.choice(MATRIX_CHARS)
                    
                    line.append(f"[{style}]{char}[/]")
                frame.append("".join(line))

            # Move cursor to the top-left and print the new frame
            console.print("\n".join(frame), end="")
            
            # Update each column's position
            for col in columns:
                col.update()
                if col.finished:
                    col.reset()

            time.sleep(interval)
    finally:
        # Always clear the screen and show the cursor when finished
        console.clear()
        console.show_cursor(True)