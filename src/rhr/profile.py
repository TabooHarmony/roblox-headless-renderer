"""Where a command's time goes, when `RHR_PROFILE=1` is set.

Phases are timed with `phase("name")` around the work; the browser page and the warm
worker report their own steps through `add()`. At exit, a table goes to stderr:
each phase with its time and share, plus the time since RHR's code started running
(Python's own start-up happens before that and is not included).
"""

from __future__ import annotations

import atexit
import os
import sys
import time
from contextlib import contextmanager

ENABLED = os.environ.get("RHR_PROFILE", "").strip() not in {"", "0", "false", "no"}
_START = time.perf_counter()
_rows: list[tuple[str, float]] = []


@contextmanager
def phase(name: str):
    if not ENABLED:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        _rows.append((name, time.perf_counter() - started))


def add(name: str, seconds: float) -> None:
    """Record a step measured elsewhere (the page, the warm worker)."""
    if ENABLED:
        _rows.append((name, float(seconds)))


def _report() -> None:
    if not ENABLED or not _rows:
        return
    total = time.perf_counter() - _START
    width = max(len(name) for name, _ in _rows)
    print(f"profile  {total * 1000:7.0f} ms since RHR started", file=sys.stderr)
    for name, seconds in _rows:
        print(f"profile    {name:<{width}}  {seconds * 1000:7.0f} ms", file=sys.stderr)


atexit.register(_report)
