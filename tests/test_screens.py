#!/usr/bin/env python3
"""ScreenGuis: every one of them renders, in paint order, and only if it is enabled.

A file can hold several ScreenGuis and Roblox draws all of them, higher DisplayOrder on
top. The engine draws exactly one root, so this pipeline renders one pass per ScreenGui
and composites. Before this, a multi-ScreenGui file rendered the top pane and silently
dropped the rest (recorded as a known gap in Task 1.7).

Run: python tests/test_screens.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURES = REPO / "tests" / "fixtures"
OUT = REPO / "out" / "screens"

RED, GREEN, BLUE, CLEAR = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (0, 0, 0, 0)

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def render(name: str, viewport: tuple[int, int], *extra: str) -> tuple:
    from PIL import Image

    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / f"{name}.png"
    proc = subprocess.run(
        [*RHR, "render", str(FIXTURES / f"{name}.rbxmx"), "--out", str(png),
         "--viewport", f"{viewport[0]}x{viewport[1]}", "--transparent", *extra],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )
    if proc.returncode != 0:
        raise SystemExit(f"render {name} failed: {proc.stderr[-300:]}")
    return Image.open(png).convert("RGBA"), proc


def main() -> int:
    print("screens: every ScreenGui renders, in paint order")

    img, proc = render("two_screen_guis", (400, 300))
    check(img.getpixel((10, 10)) == RED, f"the lower pane draws where nothing covers it ({img.getpixel((10, 10))})")
    check(img.getpixel((10, 130)) == GREEN, f"the whole lower pane draws ({img.getpixel((10, 130))})")
    check(img.getpixel((60, 60)) == BLUE, f"the higher DisplayOrder wins the overlap ({img.getpixel((60, 60))})")
    check(img.getpixel((300, 250)) == CLEAR, f"nothing draws outside the panes ({img.getpixel((300, 250))})")
    check("2 ScreenGuis rendered in paint order" in proc.stderr, "the CLI says how many panes it drew")

    # The pre-fix behaviour, asserted from the code that produced it: the pipeline used
    # to hand the engine one root, and that root was the top pane alone.
    sys.path.insert(0, str(REPO / "src"))
    from rhr.adapter import ir_to_raw_nodes
    from rhr.ir import load_ir
    from rhr.pipeline import find_renderable

    raw = ir_to_raw_nodes(load_ir(REPO / "out" / "ir" / "two_screen_guis.json"))
    single = find_renderable(raw)
    check(single is not None and single["name"] == "BluePane",
          f"one root would have been the top pane only ({single and single['name']})")

    # Studio's own models keep their main panel as bare Frames inside a Folder, with
    # ScreenGuis for dialogs. Rendering only the ScreenGuis threw that panel away, so
    # the tree outside them is a pane too, at the bottom of the stack.
    img, proc = render("folder_ui_and_dialog", (400, 300))
    check(img.getpixel((10, 10)) == GREEN,
          f"the UI outside any ScreenGui still draws ({img.getpixel((10, 10))})")
    check(img.getpixel((60, 60)) == BLUE,
          f"the dialog draws over it ({img.getpixel((60, 60))})")
    check(img.getpixel((200, 200)) == CLEAR, f"nothing else draws ({img.getpixel((200, 200))})")
    check("panes  2 ScreenGuis" in proc.stderr,
          f"the CLI counts ScreenGui panes, not the container pane ({proc.stderr.strip().splitlines()[-3:]})")

    img, proc = render("screen_gui_disabled", (300, 250))
    check(img.getpixel((150, 150)) == CLEAR,
          f"a ScreenGui with Enabled=false does not draw ({img.getpixel((150, 150))})")
    check(img.getpixel((50, 50)) == GREEN, f"the enabled pane still draws ({img.getpixel((50, 50))})")
    check("panes" not in proc.stderr, "a disabled ScreenGui is not counted as a pane")

    # A file whose only ScreenGui is disabled has no UI: a blank render, and no
    # command reports what is inside it (or calls the empty result a bug).
    disabled = FIXTURES / "screen_gui_only_disabled.rbxmx"
    img, _ = render("screen_gui_only_disabled", (300, 250))
    check(img.getbbox() is None, "an only-disabled ScreenGui paints no pixels")
    layout_path = OUT / "only-disabled-layout.json"
    proc = subprocess.run(
        [*RHR, "render", str(disabled), "--viewport", "300x250", "--transparent",
         "--out", str(OUT / "only-disabled.png"), "--dump-layout", str(layout_path)],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )
    check(proc.returncode == 0 and json.loads(layout_path.read_text())["rects"] == {},
          f"render --dump-layout accepts an intentionally blank UI ({proc.returncode})")
    for args, key in ((["layout"], "rects"), (["layout", "--rich"], "nodes"),
                      (["hitmap"], "nodes"), (["check"], "findings")):
        proc = subprocess.run(
            [*RHR, *args, str(disabled), "--viewport", "300x250"],
            capture_output=True, text=True, cwd=str(REPO), timeout=300,
        )
        result = json.loads(proc.stdout) if proc.returncode == 0 else {}
        check(proc.returncode == 0 and not result.get(key, True),
              f"{' '.join(args)} sees no disabled UI ({proc.returncode})")

    # The layout dump is the whole UI, not the pane that happens to be on top.
    dump = OUT / "two-layout.json"
    proc = subprocess.run(
        [*RHR, "layout", str(FIXTURES / "two_screen_guis.rbxmx"), "--viewport", "400x300",
         "--out", str(dump)],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )
    check(proc.returncode == 0, f"rhr layout exits 0 ({proc.stderr.strip()[:80]})")
    layout = json.loads(dump.read_text())["rects"] if dump.exists() else {}
    for path, rect in (("Under/RedPane", {"x": 0.0, "y": 0.0, "w": 100.0, "h": 100.0}),
                       ("Under/GreenStrip", {"x": 0.0, "y": 120.0, "w": 100.0, "h": 40.0}),
                       ("Over/BluePane", {"x": 50.0, "y": 50.0, "w": 100.0, "h": 100.0})):
        check(layout.get(path) == rect, f"the dump carries {path} ({layout.get(path)})")

    print("screens: ok" if not failures else f"screens: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
