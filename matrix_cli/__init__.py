from __future__ import annotations
from typing import Any

# Define what `from matrix_cli import *` will import.
__all__ = ["__version__"]


def __getattr__(name: str) -> Any:
    """
    Lazily provide `matrix_cli.__version__` from installed distribution metadata.

    This function is called by Python (per PEP 562) only when a module-level
    attribute is not found. We use it to fetch the version on-demand,
    avoiding any file I/O when the module is simply imported.
    """
    if name == "__version__":
        try:
            from importlib.metadata import version

            # The version is retrieved from package metadata only when requested
            return version("matrix-cli")
        except Exception:
            # Fallback for when metadata is missing (e.g., running from a git clone)
            return "0+unknown"
    # For any other attribute, raise the standard error.
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__() -> list[str]:
    """
    Optional: Ensures `__version__` appears in `dir(matrix_cli)` and auto-completion.
    """
    return sorted([*globals().keys(), "__version__"])
