#!/usr/bin/env python3
"""Public-path regression test for a 2D-hosted 3D ViewportFrame."""

from __future__ import annotations

import sys
import json
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-viewport-test-") as directory:
        output = Path(directory) / "viewport.png"
        layout = Path(directory) / "viewport.json"
        subprocess.run(
            [
                *RHR,
                "render",
                str(ROOT / "tests/fixtures/viewport_frame.rbxmx"),
                "--viewport",
                "440x336",
                "--out",
                str(output),
                "--dump-layout",
                str(layout),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with Image.open(output).convert("RGBA") as image:
            assert image.size == (440, 336)
            colored = []
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int, int], image.getpixel((x, y)))
                    if pixel[0] < 100 and pixel[1] > pixel[0] + 20 and pixel[2] > pixel[0] + 20:
                        colored.append((x, y))
            assert colored, "ViewportFrame produced no cyan 3D pixels"
            frame = json.loads(layout.read_text())["rects"]["ViewportFixture/Shell/Preview"]
            left = frame["x"]
            top = frame["y"]
            right = left + frame["w"]
            bottom = top + frame["h"]
            assert all(left <= x < right and top <= y < bottom for x, y in colored)
    print("viewport frame: ok")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
