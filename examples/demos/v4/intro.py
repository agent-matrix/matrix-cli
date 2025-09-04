# File: intro.py
# SPDX-License-Identifier: MIT
"""
Matrix "digital rain" intro optimized for terminal recording.

Why this works great with asciinema → agg:
  • Uses Rich Live with screen=True (alternate screen) — no scrolling frames.
  • Stable frame pacing via monotonic clock — consistent timing in casts.
  • Minimal, predictable ANSI; no noisy clears per frame.
  • Reproducible output via MATRIX_ANIM_SEED, so GIFs look crisp.

Quick capture example:
  asciinema rec -q -c "python intro.py" rain.cast
  agg --cols 120 --rows 30 rain.cast rain.gif   # adjust size to match terminal

Env overrides:
  MATRIX_ANIM_DURATION   seconds (default 2.0)
  MATRIX_ANIM_FPS        frames/sec (default 24)
  MATRIX_ANIM_SEED       int seed (default: unset/random)
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from shutil import get_terminal_size
from typing import List

try:
    from rich.console import Console
    from rich.live import Live
except ImportError:
    print("Error: The 'rich' library is not installed.")
    print("Please install it by running: pip install rich")
    raise SystemExit(1)

console = Console()

# Katakana + numerals (stylized) — small set for clean GIF dithering
MATRIX_CHARS = (
    "ﾊﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ"
    "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ"
    "0123456789"
)

def load_banner() -> str:
    """
    Load and return the ASCII banner from banner.txt in bright green.
    """
    banner_path = os.path.join(os.path.dirname(__file__), "banner.txt")
    try:
        with open(banner_path, encoding="utf-8") as f:
            return f"[bright_green]{f.read()}[/bright_green]"
    except FileNotFoundError:
        return "[bold red]Matrix Banner (banner.txt) Not Found[/]"

@dataclass
class Column:
    width: int
    height: int
    head: int
    length: int
    speed: float
    acc: float = 0.0
    finished: bool = False

    @classmethod
    def new(cls, width: int, height: int, rng: random.Random) -> "Column":
        head = rng.randint(0, height)
        length = max(3, rng.randint(height // 3, max(height - 2, 3)))
        speed = rng.uniform(0.35, 1.35)  # tuned for smooth playback at 24–30 fps
        return cls(width, height, head, length, speed)

    def reset(self, rng: random.Random) -> None:
        c = Column.new(self.width, self.height, rng)
        self.head, self.length, self.speed = c.head, c.length, c.speed
        self.acc = 0.0
        self.finished = False

    def step(self, dt_frames: float) -> None:
        """Advance head position using a fractional accumulator (fps-agnostic)."""
        self.acc += self.speed * dt_frames
        if self.acc >= 1.0:
            step = int(self.acc)
            self.head += step
            self.acc -= step
        if self.head - self.length > self.height:
            self.finished = True

class RandStream:
    """
    Very cheap pseudo-stream of characters to avoid per-cell random.choice overhead.
    """
    __slots__ = ("buf", "i", "n")
    def __init__(self, alphabet: str, size: int, rng: random.Random) -> None:
        self.buf = rng.choices(alphabet, k=size)
        self.i = 0
        self.n = size

    def next(self) -> str:
        ch = self.buf[self.i]
        self.i += 1
        if self.i >= self.n:
            self.i = 0
        return ch

def _default_input_key() -> str:
    # Placeholder for symmetry with other CLI pieces; unused here
    return "query"

def _build_frame(columns: List[Column], width: int, height: int, rstream: RandStream) -> str:
    """
    Build a full-frame markup string with minimal overhead.
    We emit short style runs instead of opening/closing per character.
    """
    lines: List[str] = []
    for y in range(height):
        out = []
        current_style = None
        run = []

        def flush_run(style: str | None) -> None:
            if not run:
                return
            text = "".join(run)
            if style:
                out.append(f"[{style}]{text}[/]")
            else:
                out.append(text)
            run.clear()

        for x in range(width):
            col = columns[x]
            # Default is background space (keep as space to minimize changes)
            ch = " "
            style = None

            # Decide if (x,y) is in the column's head or trail
            if y == col.head:
                style = "white"
                ch = rstream.next()
            else:
                tail_top = col.head
                tail_bottom = col.head - col.length
                if tail_bottom <= y < tail_top:
                    # Deeper in the tail → darker green
                    # Two bands for a classic gradient
                    if y >= tail_top - max(2, col.length // 6):
                        style = "bright_green"  # head glow
                    else:
                        style = "green"
                    ch = rstream.next()

            # Merge same-style runs to reduce markup noise
            if style == current_style:
                run.append(ch)
            else:
                flush_run(current_style)
                current_style = style
                run.append(ch)

        flush_run(current_style)
        lines.append("".join(out))
    return "\n".join(lines)

def matrix_rain(duration: float = 2.0, fps: int = 24) -> None:
    """
    Render Matrix rain in an alt screen for 'duration' seconds at 'fps'.
    Frame pacing uses a monotonic clock for stable asciinema timing.
    """
    # Reproducible captures if MATRIX_ANIM_SEED is set
    seed_env = os.getenv("MATRIX_ANIM_SEED")
    rng = random.Random(int(seed_env)) if seed_env and seed_env.isdigit() else random.Random()

    # Terminal size (asciinema typically fixes this; agg respects cast size)
    ts = get_terminal_size(fallback=(80, 24))
    width, height = ts.columns, ts.lines

    # Create columns and a shared cheap character stream
    columns = [Column.new(width, height, rng) for _ in range(width)]
    rstream = RandStream(MATRIX_CHARS, size=max(4096, width * height * 2), rng=rng)

    # Frame pacing
    dt = 1.0 / max(1, fps)
    t0 = time.monotonic()
    next_tick = t0
    elapsed = 0.0

    # Use Rich Live with alternate screen; keep it simple for cast tools
    with Live(
        "", console=console, refresh_per_second=fps, screen=True, transient=False
    ) as live:
        # Hide cursor (Live usually does, but be explicit for safety)
        console.show_cursor(False)
        try:
            frame_index = 0
            while elapsed < duration:
                # Build and draw frame
                markup = _build_frame(columns, width, height, rstream)
                # Use update(..., refresh=False) and control the pacing ourselves
                live.update(markup, refresh=True)

                # Advance columns (1 logical "frame")
                for col in columns:
                    col.step(1.0)
                    if col.finished:
                        col.reset(rng)

                frame_index += 1
                next_tick += dt
                now = time.monotonic()
                sleep_for = next_tick - now
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    # If we’re behind, drop sleep but don’t loop-catch up (keeps cast stable)
                    next_tick = now
                elapsed = now - t0
        finally:
            console.show_cursor(True)

if __name__ == "__main__":
    # Read env overrides for recording sessions
    dur = float(os.getenv("MATRIX_ANIM_DURATION", "2.0"))
    fps = int(os.getenv("MATRIX_ANIM_FPS", "24"))

    matrix_rain(duration=dur, fps=fps)
    console.print(load_banner(), justify="center")
    console.print("\n[bold cyan]Welcome to the Matrix CLI v0.1.5 [/bold cyan]\n", justify="center")
