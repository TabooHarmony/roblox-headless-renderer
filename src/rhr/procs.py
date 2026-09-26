"""Options for the helper processes RHR starts (Lune, Rojo, workers).

On Windows a console program started by a process with no console of its own (an
agent, an MCP host, a GUI) gets a new console window, which takes the focus. These
helpers never need one, so they are started with a hidden console; their children
share it and stay hidden too.
"""

from __future__ import annotations

import subprocess
import sys


def no_window() -> dict:
    """subprocess keyword arguments that start a console program without a window."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
