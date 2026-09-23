#!/usr/bin/env python3
"""Rojo projects are accepted anywhere a Roblox file is.

`tests/fixtures/rojo_hud/` is a model project: a ScreenGui with a Frame declared
inline and a TextLabel from a `.model.json` file. The directory and its
default.project.json both work as input to layout, render, check and ir; without
`rojo` on PATH the CLI says how to install it.

    python tests/test_rojo.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
PROJECT_DIR = ROOT / "tests" / "fixtures" / "rojo_hud"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=180, env=env)


def main() -> int:
    print("rojo: project directory and project file as input")
    for source in (PROJECT_DIR, PROJECT_DIR / "default.project.json"):
        proc = run(["layout", str(source), "--viewport", "400x300", "--topbar-height", "0"])
        check(proc.returncode == 0, f"layout {source.name} exits 0 {proc.stderr[-300:] if proc.returncode else ''}")
        if proc.returncode == 0:
            layout = json.loads(proc.stdout)["rects"]
            check(layout.get("RojoHud/Panel") == {"x": 20.0, "y": 30.0, "w": 200.0, "h": 100.0},
                  f"inline Frame from the project tree: {layout.get('RojoHud/Panel')}")
            check(layout.get("RojoHud/Panel/Badge") == {"x": 30.0, "y": 40.0, "w": 80.0, "h": 24.0},
                  f"TextLabel from a .model.json file: {layout.get('RojoHud/Panel/Badge')}")

    with tempfile.TemporaryDirectory(prefix="rhr-rojo-") as directory:
        tmp = Path(directory)
        proc = run(["render", str(PROJECT_DIR), "--viewport", "400x300", "--out", str(tmp / "hud.png")])
        check(proc.returncode == 0 and (tmp / "hud.png").is_file(), "render builds and draws the project")
        proc = run(["check", str(PROJECT_DIR)])
        check(proc.returncode == 0 and "findings" in proc.stdout, "check runs on the project")
        proc = run(["ir", str(PROJECT_DIR), "--out", str(tmp / "hud.json")])
        check(proc.returncode == 0 and (tmp / "hud.json").is_file(), "ir writes the project's IR")

    print("rojo: a missing rojo is a clear error")
    env = dict(os.environ, PATH=str(Path(sys.executable).parent))
    proc = run(["layout", str(PROJECT_DIR)], env=env)
    check(proc.returncode != 0 and "rojo" in proc.stderr and "rokit add" in proc.stderr,
          f"install hint on stderr: {proc.stderr.strip()[-200:]}")

    print(f"rojo: {len(failures)} failed" if failures else "rojo: ok")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
