#!/usr/bin/env python3
"""Browser scene smoke test: the public CLI must produce visible 3D pixels."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "scene_geometry.rbxmx"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-scene-test-") as directory:
        out = Path(directory) / "scene.png"
        result = subprocess.run(
            [
                str(REPO / "bin" / "rhr"),
                "scene",
                str(FIXTURE),
                "--viewport",
                "400x300",
                "--out",
                str(out),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode
        with Image.open(out) as image:
            rgb = image.convert("RGB")
            pixels = list(rgb.get_flattened_data())
            visible = len(set(pixels)) > 1
            dimensions = rgb.size
        print(f"scene: {dimensions[0]}x{dimensions[1]}, {len(set(pixels))} colors")
        if dimensions != (400, 300) or not visible:
            print("scene: FAIL: output is blank or has the wrong dimensions")
            return 1
    with tempfile.TemporaryDirectory(prefix="rhr-wedge-test-") as directory:
        out = Path(directory) / "wedge.png"
        result = subprocess.run(
            [
                str(REPO / "bin" / "rhr"), "scene",
                str(REPO / "tests" / "fixtures" / "scene_wedge.rbxmx"),
                "--viewport", "400x300", "--out", str(out),
            ], cwd=REPO, capture_output=True, text=True, timeout=60
        )
        if result.returncode:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode
        with Image.open(out).convert("RGB") as image:
            green = []
            for y in range(image.height):
                for x in range(image.width):
                    r, g, b = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if g > r * 1.5 and g > b * 1.2 and g > 60:
                        green.append((x, y))
            tops = [min(y for xx, y in green if xx == x) for x in {xx for xx, _ in green}]
            if len(green) < 3000 or max(tops) - min(tops) < 40:
                print("scene: FAIL: wedge did not produce a sloped silhouette")
                return 1
            blue = []
            for y in range(image.height):
                for x in range(image.width):
                    r, g, b = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if b > r * 1.5 and b > g * 1.5 and b > 60:
                        blue.append((x, y))
            blue_tops = [min(y for xx, y in blue if xx == x) for x in {xx for xx, _ in blue}]
            if len(blue) < 1500 or max(blue_tops) - min(blue_tops) < 25:
                print("scene: FAIL: corner wedge did not produce a diagonal silhouette")
                return 1
        print(f"wedge: green_pixels={len(green)} top_edge_range={max(tops) - min(tops)}")
    print("scene: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
