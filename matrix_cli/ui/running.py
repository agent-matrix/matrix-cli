# Example usage in another file (e.g., matrix_cli/commands/search.py)

import time
from matrix_cli.ui.loading import start_loading_animation, stop_loading_animation
from rich.console import Console

console = Console()

def some_long_running_task():
    """
    A placeholder function to simulate a task that takes time.
    """
    console.print("[yellow]Starting a long-running task...[/yellow]")
    
    # Start the loading animation
    animation_thread, stop_event = start_loading_animation()

    try:
        # Simulate work being done
        time.sleep(5)  # Replace this with your actual task
        
        # Simulate more work
        console.print("[yellow]Still working...[/yellow]")
        time.sleep(5)

    finally:
        # Stop the animation when the task is done
        stop_loading_animation(animation_thread, stop_event)

    console.print("[bold green]Task completed successfully![/bold green]")

if __name__ == "__main__":
    some_long_running_task()