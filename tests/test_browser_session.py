#!/usr/bin/env python3
"""Persistent browser worker reuses Chromium without changing rendered pixels."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests/fixtures/scene_geometry.rbxmx"


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(RHR), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def main() -> None:
    stop = run("browser", "stop")
    assert stop.returncode == 0, stop.stderr

    with tempfile.TemporaryDirectory(prefix="rhr-browser-session-") as directory:
        tmp = Path(directory)
        legacy = tmp / "legacy.png"
        first = tmp / "first.png"
        second = tmp / "second.png"

        env_legacy = dict(os.environ, RHR_PERSISTENT_BROWSER="0")
        proc = run(
            "scene", str(FIXTURE),
            "--viewport", "400x300",
            "--out", str(legacy),
            env=env_legacy,
        )
        assert proc.returncode == 0, proc.stderr

        start = run("browser", "start")
        assert start.returncode == 0, start.stderr
        started = json.loads(start.stdout)
        assert started["running"] is True
        pid = started["pid"]

        status = run("browser", "status")
        assert status.returncode == 0, status.stderr
        current = json.loads(status.stdout)
        assert current["running"] is True
        assert current["pid"] == pid

        for output in (first, second):
            proc = run(
                "scene", str(FIXTURE),
                "--viewport", "400x300",
                "--out", str(output),
            )
            assert proc.returncode == 0, proc.stderr
            current = json.loads(run("browser", "status").stdout)
            assert current["pid"] == pid, (pid, current)

        assert legacy.read_bytes() == first.read_bytes() == second.read_bytes()

    stop = run("browser", "stop")
    assert stop.returncode == 0, stop.stderr
    stopped = json.loads(stop.stdout)
    assert stopped["running"] is False
    assert json.loads(run("browser", "status").stdout)["running"] is False

    print(f"browser session: reused pid={pid}, byte-identical renders")


if __name__ == "__main__":
    main()
