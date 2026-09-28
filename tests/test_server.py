#!/usr/bin/env python3
"""The resident server (rhr.server) and its client (rhr.client, what `rhr` runs).

A command through the server must be indistinguishable from the same command run in
its own process: the same stdout bytes, the same exit code, stderr carrying the same
messages. Also: parallel commands (one gets the server, the others run in their own
process), and `rhr server stop`.

Run: python tests/test_server.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
UI = REPO / "tests" / "fixtures" / "grid_offset.rbxmx"
ERRORS = REPO / "tests" / "fixtures" / "zero_grid_cell.rbxmx"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def run(*args: str, server: bool) -> subprocess.CompletedProcess:
    env = dict(os.environ, RHR_SERVER="1" if server else "0")
    return subprocess.run([*RHR, *args], capture_output=True, cwd=str(REPO), env=env, timeout=300)


def main() -> int:
    print("server: same output as a process of its own")
    try:
        for args in (["layout", str(UI)], ["check", str(UI)], ["hitmap", str(UI)],
                     ["check", str(ERRORS)], ["layout", "missing.rbxm"], ["layout", str(UI), "--bogus"]):
            run(*args, server=False)  # converts the file: every run below reuses it
            here = run(*args, server=False)
            first = run(*args, server=True)   # starts the server
            second = run(*args, server=True)  # a warm one
            label = " ".join(Path(a).name if "/" in a or "\\" in a else a for a in args)
            for name, served in (("first", first), ("warm", second)):
                check(served.stdout == here.stdout, f"{label}: {name} stdout identical")
                check(served.returncode == here.returncode,
                      f"{label}: {name} exit code {served.returncode} == {here.returncode}")
                # stderr: the same lines, except timings.
                strip = lambda text: [line for line in text.decode("utf-8", "replace").splitlines()  # noqa: E731
                                      if "ms" not in line and "reused" not in line]
                check(strip(served.stderr) == strip(here.stderr), f"{label}: {name} stderr lines identical")

        print("server: parallel commands all succeed")
        expected = run("layout", str(UI), server=False).stdout
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: run("layout", str(UI), server=True), range(4)))
        check(all(r.returncode == 0 and r.stdout == expected for r in results), "4 at once: same output")
    finally:
        stopped = run("server", "stop", server=True)
        check(stopped.returncode == 0 and b"stopped" in stopped.stderr,
              f"rhr server stop ({stopped.stderr.decode('utf-8', 'replace').strip()})")
    again = run("server", "stop", server=True)
    check(b"no server" in again.stderr, "a second stop finds none")

    print("server: an idle server lets go of loaded files beyond its budget")
    sys.path.insert(0, str(REPO / "src"))
    from rhr import ir

    ir.trim_loaded(0)
    paths = [ir.cached_ir(REPO / "tests" / "fixtures" / name, profile="ui")
             for name in ("grid_offset.rbxmx", "ir_profiles.rbxmx")]
    for path in paths:
        ir.load_ir(path)
    sizes = [path.stat().st_size for path in paths]
    check(ir.trim_loaded(sum(sizes)) == 0 and len(ir._LOADED) == 2, "within the budget: both kept")
    check(ir.trim_loaded(sizes[1]) == 1 and len(ir._LOADED) == 1, "over it: the least recently read goes first")
    check(ir.trim_loaded(0) == 1 and not ir._LOADED, "a budget of 0 lets go of everything")

    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    print("\nall server checks passed")
    return 0


def test_server():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
