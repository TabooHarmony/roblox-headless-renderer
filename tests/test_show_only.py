#!/usr/bin/env python3
"""Screens that code opens, and UI commands with nothing to draw.

`tests/fixtures/closed_screens.rbxmx`: a HUD that is on, and a Menus ScreenGui saved
closed (Enabled = false) holding a hidden Shop page (Visible = false) and an
Inventory. `--show PATH` opens PATH and what holds it; `--only PATH` draws it with
every other screen closed. `tests/fixtures/all_closed.rbxmx` has only a closed
screen: every UI command exits 2 and says how to draw it, never 0 with nothing.

    python tests/test_show_only.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
CLOSED = ROOT / "tests" / "fixtures" / "closed_screens.rbxmx"
ALL_CLOSED = ROOT / "tests" / "fixtures" / "all_closed.rbxmx"
PROJECT = ROOT / "tests" / "fixtures" / "rojo_hud"

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=180)


def rects(*extra: str) -> set[str]:
    proc = run("layout", str(CLOSED), "--topbar-height", "0", *extra)
    check(proc.returncode == 0, f"layout {' '.join(extra) or '(default)'} exits 0 {proc.stderr[-300:]}")
    return set(json.loads(proc.stdout)["rects"]) if proc.returncode == 0 else set()


def main() -> int:
    print("show/only: which screens are drawn")
    check(rects() == {"Hud/Coins"}, "by default, only what is saved open")
    check(rects("--show", "Menus/Shop") == {"Hud/Coins", "Menus/Shop", "Menus/Shop/Buy", "Menus/Inventory"},
          "--show opens the page and its closed ScreenGui, on top of the rest")
    check(rects("--only", "Menus/Shop") == {"Menus/Shop", "Menus/Shop/Buy"},
          "--only draws the page alone: other screens and its siblings closed")
    check(rects("--only", "Menus") == {"Menus/Inventory"}, "--only a ScreenGui: as saved inside it")
    check(rects("--show", "Menus/Shop", "--show", "Menus") >= {"Menus/Shop", "Menus/Inventory"}, "--show repeats")

    proc = run("hitmap", str(CLOSED), "--only", "Menus/Shop")
    nodes = [node["path"] for node in json.loads(proc.stdout)["nodes"]] if proc.returncode == 0 else []
    check(nodes == ["Menus/Shop/Buy"], f"hitmap --only: the shown screen's button {nodes}")
    proc = run("check", str(CLOSED), "--only", "Menus/Shop")
    check(proc.returncode in (0, 1) and "findings" in proc.stdout, "check --only runs")
    with tempfile.TemporaryDirectory(prefix="rhr-show-") as directory:
        out = Path(directory) / "shop.png"
        proc = run("ui", str(CLOSED), "--only", "Menus/Shop", "--out", str(out))
        check(proc.returncode == 0 and out.is_file(), "ui --only draws")
    proc = run("layout", str(CLOSED), "--only", "Menus/Nope")
    check(proc.returncode == 2 and "Menus/Nope" in proc.stderr, f"an unknown path is an error: {proc.stderr[-120:]}")

    print("show/only: nothing to draw is an error with a way out")
    for command in ("ui", "layout", "check", "hitmap"):
        proc = run(command, str(ALL_CLOSED))
        check(proc.returncode == 2, f"{command} exits 2 (got {proc.returncode})")
        check("no UI to draw" in proc.stderr and "Enabled = false" in proc.stderr and "Shop" in proc.stderr
              and "--show" in proc.stderr, f"{command} says why and how: {proc.stderr.strip()[-200:]}")
        check(proc.stdout.strip() == "", f"{command} prints no document")
    proc = run("layout", str(ALL_CLOSED), "--show", "Shop")
    check(proc.returncode == 0 and "Shop/Page" in proc.stdout, "and --show draws it")

    print("show/only: a Rojo project that maps only code")
    with tempfile.TemporaryDirectory(prefix="rhr-code-only-") as directory:
        project = Path(directory)
        (project / "src").mkdir()
        (project / "src" / "Main.luau").write_text("return {}\n", encoding="utf-8")
        (project / "Game.rbxl").write_bytes(b"")
        (project / "default.project.json").write_text(json.dumps({
            "name": "CodeOnly", "servePlaceIds": [123],
            "tree": {"$className": "DataModel", "$ignoreUnknownInstances": True,
                     "ReplicatedStorage": {"$ignoreUnknownInstances": True, "$path": "src"}},
        }), encoding="utf-8")
        proc = run("ui", str(project), "--out", str(project / "x.png"))
    check(proc.returncode == 2 and "ignores unknown instances" in proc.stderr and "Game.rbxl" in proc.stderr
          and "123" in proc.stderr, f"points at the place file and id: {proc.stderr.strip()[-250:]}")

    print(f"show/only: {len(failures)} failed" if failures else "show/only: ok")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
