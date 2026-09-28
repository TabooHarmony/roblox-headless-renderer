#!/usr/bin/env python3
"""`rhr batch` runs several commands in one call.

Each result must carry what the command prints on its own (stdout parsed when it is
JSON), its exit code, and its stderr; a failing command does not stop the rest, and
the batch exits with the worst code. Commands that manage RHR are refused.

    python tests/test_batch.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
UI = str(ROOT / "tests" / "fixtures" / "grid_offset.rbxmx")
ERRORS = str(ROOT / "tests" / "fixtures" / "zero_grid_cell.rbxmx")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=300)


def main() -> None:
    commands = [["layout", UI], ["check", ERRORS], ["hitmap", UI], ["layout", "missing.rbxm"]]
    alone = [run(*command) for command in commands]
    joined: list[str] = []
    for command in commands:
        joined += [*(["+"] if joined else []), *command]
    proc = run("batch", *joined)
    document = json.loads(proc.stdout)
    assert document["schema"] == "rhr.batch/1"
    results = document["results"]
    assert [result["command"] for result in results] == commands
    for command, result, single in zip(commands, results, alone):
        assert result["exitCode"] == single.returncode, (command, result["exitCode"], single.returncode)
        expected = json.loads(single.stdout) if single.stdout.strip() else ""
        assert result["stdout"] == expected, f"{command[0]}: stdout differs from the command alone"
    assert "no such file" in results[3]["stderr"]
    assert proc.returncode == max(single.returncode for single in alone) == 2

    refused = run("batch", "layout", UI, "+", "setup")
    assert refused.returncode == 2 and "setup" in refused.stderr, refused.stderr
    print(f"batch: {len(commands)} commands, each result the same as the command alone")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
