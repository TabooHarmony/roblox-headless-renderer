#!/usr/bin/env python3
"""The long-lived command worker (used by rhr-mcp) runs command after command in one process.

Each reply is one JSON line with the command's exit code and captured output; a failing
command is reported, not fatal, and the worker goes on answering.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "rhr.command_worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1, cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
    )
    requests = [["--version"], ["cache"], ["scene", "no-such-file.rbxm"], ["--version"]]
    replies = []
    try:
        for args in requests:
            process.stdin.write(json.dumps({"args": args}) + "\n")
            process.stdin.flush()
            replies.append(json.loads(process.stdout.readline()))
        # Still answering after the failure.
        process.stdin.write(json.dumps({"args": ["--version"]}) + "\n")
        process.stdin.flush()
        replies.append(json.loads(process.stdout.readline()))
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    version, cache, missing, again, last = replies
    assert version["code"] == 0 and version["stdout"].startswith("rhr "), version
    assert cache["code"] == 0 and "total" in cache["stdout"], cache
    assert missing["code"] != 0 and "no such file" in missing["stderr"], missing
    assert again == version and last == version, (again, last)
    print(f"command worker: {len(replies)} commands in one process, failures reported, replies intact")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
