# matrix_cli/ui/loading.py

import time
import random
import threading
from shutil import get_terminal_size
from rich.console import Console

console = Console()

# Katakana and symbols inspired by The Matrix film
MATRIX_CHARS = (
    "ﾊﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ"  # Common katakana
    "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ"  # Additional katakana
    "0123456789"            # Numerals for variety
)

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

def _matrix_rain_animation(stop_event: threading.Event, fps: int = 24):
    """
    The core animation loop that runs in a background thread.
    """
    console.show_cursor(False)
    
    width, height = get_terminal_size()
    columns = [Column(width, height) for _ in range(width)]
    
    interval = 1.0 / fps

    try:
        while not stop_event.is_set():
            frame = []
            for y in range(height):
                line = []
                for x in range(width):
                    col = columns[x]
                    char = " "
                    style = "black"

                    if y == col.head:
                        style = "white"
                        char = random.choice(MATRIX_CHARS)
                    elif col.head > y > col.head - col.length:
                        style = "bright_green"
                        char = random.choice(MATRIX_CHARS)
                    elif col.head - col.length <= y <= col.head:
                        style = "green"
                        char = random.choice(MATRIX_CHARS)
                    
                    line.append(f"[{style}]{char}[/]")
                frame.append("".join(line))

            console.print("\n".join(frame), end="")
            
            for col in columns:
                col.update()
                if col.finished:
                    col.reset()

            time.sleep(interval)
    finally:
        console.clear()
        console.show_cursor(True)

def start_loading_animation():
    """
    Starts the Matrix loading animation in a background thread.
    
    Returns a tuple containing the thread object and the stop event.
    """
    stop_event = threading.Event()
    animation_thread = threading.Thread(
        target=_matrix_rain_animation,
        args=(stop_event,),
        daemon=True
    )
    animation_thread.start()
    return animation_thread, stop_event

def stop_loading_animation(animation_thread: threading.Thread, stop_event: threading.Event):
    """
    Stops the loading animation.
    """
    stop_event.set()
    animation_thread.join()# matrix_cli/ui/loading.py

import time
import random
import threading
from shutil import get_terminal_size
from rich.console import Console

console = Console()

# Katakana and symbols inspired by The Matrix film
MATRIX_CHARS = (
    "ﾊﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ"  # Common katakana
    "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ"  # Additional katakana
    "0123456789"            # Numerals for variety
)

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

def _matrix_rain_animation(stop_event: threading.Event, fps: int = 24):
    """
    The core animation loop that runs in a background thread.
    """
    console.show_cursor(False)
    
    width, height = get_terminal_size()
    columns = [Column(width, height) for _ in range(width)]
    
    interval = 1.0 / fps

    try:
        while not stop_event.is_set():
            frame = []
            for y in range(height):
                line = []
                for x in range(width):
                    col = columns[x]
                    char = " "
                    style = "black"

                    if y == col.head:
                        style = "white"
                        char = random.choice(MATRIX_CHARS)
                    elif col.head > y > col.head - col.length:
                        style = "bright_green"
                        char = random.choice(MATRIX_CHARS)
                    elif col.head - col.length <= y <= col.head:
                        style = "green"
                        char = random.choice(MATRIX_CHARS)
                    
                    line.append(f"[{style}]{char}[/]")
                frame.append("".join(line))

            console.print("\n".join(frame), end="")
            
            for col in columns:
                col.update()
                if col.finished:
                    col.reset()

            time.sleep(interval)
    finally:
        console.clear()
        console.show_cursor(True)

def start_loading_animation():
    """
    Starts the Matrix loading animation in a background thread.
    
    Returns a tuple containing the thread object and the stop event.
    """
    stop_event = threading.Event()
    animation_thread = threading.Thread(
        target=_matrix_rain_animation,
        args=(stop_event,),
        daemon=True
    )
    animation_thread.start()
    return animation_thread, stop_event

def stop_loading_animation(animation_thread: threading.Thread, stop_event: threading.Event):
    """
    Stops the loading animation.
    """
    stop_event.set()
    animation_thread.join()