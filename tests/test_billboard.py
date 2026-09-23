#!/usr/bin/env python3
"""Public-path regression test for a BillboardGui overlay."""

from __future__ import annotations

import sys
import subprocess
import tempfile
import json
from pathlib import Path
from typing import cast

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-billboard-test-") as directory:
        output = Path(directory) / "billboard.png"
        ir_output = Path(directory) / "billboard.json"
        subprocess.run(
            [*RHR, "ir", str(ROOT / "tests/fixtures/billboard_gui.rbxmx"), "--out", str(ir_output)],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ir = json.loads(ir_output.read_text())
        billboards = []
        def collect(node):
            if node.get("className") == "BillboardGui":
                billboards.append(node)
            for child in node.get("children", []):
                collect(child)
        for root in ir["roots"]:
            collect(root)
        assert [node["props"].get("Adornee") for node in billboards] == ["BillboardWorld.SignPost"]
        assert billboards[0]["props"].get("SizeOffset") == {"X": 0.5, "Y": 0.5, "_t": "Vector2"}
        assert billboards[0]["props"].get("ExtentsOffset") == {"X": 1, "Y": 0, "Z": 0, "_t": "Vector3"}
        subprocess.run(
            [
                *RHR,
                "scene",
                str(ROOT / "tests/fixtures/billboard_gui.rbxmx"),
                "--viewport",
                "500x350",
                "--out",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with Image.open(output).convert("RGB") as image:
            assert image.size == (500, 350)
            orange = []
            dark_text = 0
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if pixel[0] > 180 and 80 < pixel[1] < 190 and pixel[2] < 90:
                        orange.append((x, y))
            assert len(orange) > 100, "BillboardGui panel did not render"
            left = min(x for x, _ in orange)
            right = max(x for x, _ in orange)
            top = min(y for _, y in orange)
            bottom = max(y for _, y in orange)
            assert 265 < left < 280 and 325 < right < 345
            assert 120 < top < 145 and 145 < bottom < 165
            for y in range(top, bottom + 1):
                for x in range(left, right + 1):
                    red, green, blue = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if red < 80 and green < 80 and blue < 80:
                        dark_text += 1
            assert dark_text > 10, "BillboardGui text did not render inside the panel"

    with tempfile.TemporaryDirectory(prefix="rhr-billboard-offset-test-") as directory:
        output = Path(directory) / "billboard-offset.png"
        subprocess.run(
            [
                *RHR, "scene",
                str(ROOT / "tests/fixtures/billboard_offset.rbxmx"),
                "--viewport", "500x350", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            orange = []
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if pixel[0] > 180 and 80 < pixel[1] < 190 and pixel[2] < 90:
                        orange.append((x, y))
            # The 120x32 panel is 3840 px; the label's text (drawn by the 2D engine
            # in the model's font) covers part of it. The exact bbox checks follow.
            assert len(orange) > 2500, "offset-sized BillboardGui panel did not render"
            left = min(x for x, _ in orange)
            right = max(x for x, _ in orange)
            top = min(y for _, y in orange)
            bottom = max(y for _, y in orange)
            assert 188 <= left <= 192 and 307 <= right <= 311, (left, right)
            assert 135 <= top <= 139 and 166 <= bottom <= 170, (top, bottom)
            assert right - left + 1 == 120
            assert bottom - top + 1 == 32

    with tempfile.TemporaryDirectory(prefix="rhr-billboard-layout-test-") as directory:
        output = Path(directory) / "billboard-layout.png"
        subprocess.run(
            [
                *RHR, "scene",
                str(ROOT / "tests/fixtures/inworld_child_layout.rbxmx"),
                "--viewport", "500x350", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            orange = []
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if pixel[0] > 180 and 90 < pixel[1] < 180 and pixel[2] < 80:
                        orange.append((x, y))
            assert len(orange) > 300, "positioned BillboardGui child did not render"
            assert 228 < min(x for x, _ in orange) < 240
            assert 260 < max(x for x, _ in orange) < 272
            assert 142 < min(y for _, y in orange) < 154
            assert 153 < max(y for _, y in orange) < 165
    print("billboard: ok")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
