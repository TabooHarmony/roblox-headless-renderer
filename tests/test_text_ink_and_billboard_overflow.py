#!/usr/bin/env python3
"""Two differences a Studio side-by-side showed (the README picture, 2026-09-28).

1. Fredoka One (a face with a Studio advance table) drew about 0.82x too small:
   the table was looked up at the font's em size instead of the Roblox TextSize.
   Studio's ink for "Sample Price" at TextSize 26 is 137x22 px, as wide as its
   TextBounds (138). The drawn ink must be as wide as the laid-out text.
2. A BillboardGui with ClipsDescendants off was cut at its own size: a 1-stud
   billboard with a label five times as wide showed a few letters. Roblox draws
   the whole label.

    python tests/test_text_ink_and_billboard_overflow.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]


def udim2(xs, xo, ys, yo):
    return {"_t": "UDim2", "XS": xs, "XO": xo, "YS": ys, "YO": yo}


def color(r, g, b):
    return {"_t": "Color3", "R": r, "G": g, "B": b}


def fredoka_ir() -> dict:
    label = {"className": "TextLabel", "name": "Price", "children": [], "props": {
        "Text": "Sample Price", "TextSize": 26, "TextScaled": False, "TextColor3": color(1, 1, 1),
        "FontFace": {"_t": "Font", "family": "rbxasset://fonts/families/FredokaOne.json",
                     "style": "Enum.FontStyle.Normal", "weight": "Enum.FontWeight.Regular"},
        "BackgroundColor3": color(0, 0, 0), "BackgroundTransparency": 0,
        "Position": udim2(0, 20, 0, 20), "Size": udim2(0, 200, 0, 40)}}
    gui = {"className": "ScreenGui", "name": "Gui", "props": {"IgnoreGuiInset": True}, "children": [label]}
    return {"sourcePath": "fredoka", "roots": [{"className": "StarterGui", "name": "StarterGui", "props": {}, "children": [gui]}]}


def billboard_ir(clips: bool) -> dict:
    label = {"className": "TextLabel", "name": "Sign", "children": [], "props": {
        "Text": "WIDE SIGN", "TextScaled": True, "TextSize": 30, "TextColor3": color(1, 0, 0),
        "BackgroundTransparency": 1, "AnchorPoint": {"_t": "Vector2", "X": 0.5, "Y": 0.5},
        "Position": udim2(0.5, 0, 0.5, 0), "Size": udim2(5, 0, 1, 0)}}
    board = {"className": "BillboardGui", "name": "Board", "children": [label], "props": {
        "Size": udim2(1, 0, 1, 0), "AlwaysOnTop": True, "ClipsDescendants": clips, "MaxDistance": 1000}}
    post = {"className": "Part", "name": "Post", "children": [board], "props": {
        "CFrame": {"_t": "CFrame", "X": 0, "Y": 3, "Z": 0, "R00": 1, "R01": 0, "R02": 0, "R10": 0, "R11": 1,
                   "R12": 0, "R20": 0, "R21": 0, "R22": 1},
        "Size": {"_t": "Vector3", "X": 1, "Y": 1, "Z": 1}, "Transparency": 1, "Color": color(0.5, 0.5, 0.5),
        "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256}}}
    return {"sourcePath": "billboard", "roots": [{"className": "Workspace", "name": "Workspace", "props": {}, "children": [post]}]}


def run(*args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    return proc


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-ink-") as directory:
        tmp = Path(directory)

        source = tmp / "fredoka.json"
        source.write_text(json.dumps(fredoka_ir()), encoding="utf-8")
        run("ui", str(source), "--viewport", "300x100", "--topbar-height", "0", "--out", str(tmp / "fredoka.png"))
        layout = json.loads(run("layout", str(source), "--viewport", "300x100", "--topbar-height", "0", "--rich").stdout)
        bounds = next(n for n in layout["nodes"] if n["path"].endswith("Price"))["text"]["bounds"]
        pixels = np.asarray(Image.open(tmp / "fredoka.png").convert("RGB")).astype(int)
        ys, xs = np.nonzero((pixels[20:60, 20:220] > 200).all(axis=2))
        ink_w, ink_h = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        assert abs(ink_w - bounds[0]) <= 4, f"Fredoka ink {ink_w} px wide for text laid out {bounds[0]} px wide"
        assert ink_h >= 0.8 * 26, f"Fredoka ink {ink_h} px tall at TextSize 26 (Studio: 22)"

        widths = {}
        for clips in (True, False):
            source = tmp / f"billboard-{clips}.json"
            source.write_text(json.dumps(billboard_ir(clips)), encoding="utf-8")
            out = tmp / f"billboard-{clips}.png"
            run("scene", str(source), "--camera=0,3,-12", "--look-at=0,3,0", "--fov", "60", "--viewport", "600x300",
                "--out", str(out))
            pixels = np.asarray(Image.open(out).convert("RGB")).astype(int)
            red = (pixels[..., 0] > 180) & (pixels[..., 1] < 80) & (pixels[..., 2] < 80)
            xs = np.nonzero(red.any(axis=0))[0]
            widths[clips] = int(xs.max() - xs.min() + 1) if len(xs) else 0
        assert widths[False] > 2.5 * max(widths[True], 1), f"billboard text widths (clipped, not clipped): {widths}"
    print(f"ink {ink_w}x{ink_h} for bounds {bounds}; billboard text {widths[True]} px clipped, {widths[False]} px not")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
