"""One Lune process that converts file after file (luau/rhr-ir-serve.luau).

Used by the resident server (rhr.server), where the same process converts every edit
an agent makes: starting Lune and compiling rhr-ir.luau is about half a second, most
of what a small XML model's conversion takes. A command in a process of its own runs
Lune once, as before (rhr.ir.emit_ir).
"""

from __future__ import annotations

import atexit
import subprocess
import threading
from pathlib import Path

from rhr.paths import LUAU_IR_SCRIPT
from rhr.procs import no_window

SERVE_SCRIPT = LUAU_IR_SCRIPT.with_name("rhr-ir-serve.luau")
END = "\x1e"

_worker: subprocess.Popen | None = None
_worker_lune: str | None = None
_lock = threading.Lock()


def _start(lune: str) -> subprocess.Popen:
    return subprocess.Popen(
        [lune, "run", str(SERVE_SCRIPT), str(LUAU_IR_SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # rbx-dom's warnings; failures come back as replies
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **no_window(),
    )


def convert(lune: str, source: Path, out: Path, profile: str) -> tuple[int, str, str]:
    """(exit code, stdout, stderr) as a `lune run rhr-ir.luau source out profile` would
    give them; a failure is exit code 1 with the reason as stderr."""
    global _worker, _worker_lune
    request = f"{source}\t{out}\t{profile}\n"
    if "\t" in str(source) + str(out) or "\n" in str(source) + str(out):
        raise ValueError("path not usable with the Lune worker")
    with _lock:
        for attempt in (1, 2):
            if _worker is None or _worker.poll() is not None or _worker_lune != lune:
                stop()
                _worker, _worker_lune = _start(lune), lune
            try:
                _worker.stdin.write(request)
                _worker.stdin.flush()
                lines = []
                while True:
                    line = _worker.stdout.readline()
                    if not line:
                        raise OSError("the Lune worker exited")
                    if line.startswith(END):
                        status = line[1:].rstrip("\r\n")
                        break
                    lines.append(line)
            except OSError:
                stop()
                if attempt == 2:
                    raise
                continue
            stdout = "".join(lines)
            if status == "ok":
                return 0, stdout, ""
            return 1, stdout, status.removeprefix("error ")
    raise OSError("the Lune worker did not answer")


def stop() -> None:
    global _worker
    worker, _worker = _worker, None
    if worker is None:
        return
    try:
        worker.stdin.close()
        worker.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        worker.kill()


atexit.register(stop)
