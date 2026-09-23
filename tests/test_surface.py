#!/usr/bin/env python3
"""Public-path regression test for a SurfaceGui face overlay."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import cast

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-surface-test-") as directory:
        output = Path(directory) / "surface.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_gui.rbxmx"),
                "--viewport", "500x350", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            assert image.size == (500, 350)
            green = []
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if pixel[1] > 150 and pixel[0] < 100 and pixel[2] < 150:
                        green.append((x, y))
            assert len(green) > 100, "SurfaceGui panel did not render"
            assert 150 < min(x for x, _ in green) < 230
            assert 270 < max(x for x, _ in green) < 350
            assert 100 < min(y for _, y in green) < 170
            assert 190 < max(y for _, y in green) < 250

    with tempfile.TemporaryDirectory(prefix="rhr-surface-depth-test-") as directory:
        output = Path(directory) / "surface-depth.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_depth.rbxmx"),
                "--viewport", "300x300", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            center = cast(tuple[int, int, int], image.getpixel((150, 150)))
            assert center[1] > 180 and center[0] < 80 and center[2] < 80, (
                f"near SurfaceGui did not win overlap: {center}"
            )

    with tempfile.TemporaryDirectory(prefix="rhr-surface-zoffset-test-") as directory:
        output = Path(directory) / "surface-zoffset.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_zoffset.rbxmx"),
                "--viewport", "300x300", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            center = cast(tuple[int, int, int], image.getpixel((150, 150)))
            assert center[1] > 180 and center[0] < 80 and center[2] < 80, (
                f"higher SurfaceGui ZOffset did not win same-face overlap: {center}"
            )

    with tempfile.TemporaryDirectory(prefix="rhr-surface-max-distance-test-") as directory:
        output = Path(directory) / "surface-max-distance.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_max_distance.rbxmx"),
                "--viewport", "300x300", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            center = cast(tuple[int, int, int], image.getpixel((150, 150)))
            expected_background = (179, 186, 199)
            assert max(abs(actual - expected) for actual, expected in zip(center, expected_background)) <= 8, (
                f"SurfaceGui beyond MaxDistance still rendered: {center}"
            )

    with tempfile.TemporaryDirectory(prefix="rhr-surface-oblique-test-") as directory:
        output = Path(directory) / "surface-oblique.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_oblique.rbxmx"),
                "--viewport", "500x350", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            green = []
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if pixel[1] > 150 and pixel[0] < 100 and pixel[2] < 150:
                        green.append((x, y))
            assert len(green) > 9000, "oblique SurfaceGui content did not render"
            assert 185 < min(x for x, _ in green) < 200
            assert 300 < max(x for x, _ in green) < 315
            assert 120 < min(y for _, y in green) < 135
            assert 215 < max(y for _, y in green) < 230

    with tempfile.TemporaryDirectory(prefix="rhr-surface-right-test-") as directory:
        output = Path(directory) / "surface-right.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_right.rbxmx"),
                "--viewport", "500x350", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            green = []
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if pixel[1] > 150 and pixel[0] < 100 and pixel[2] < 150:
                        green.append((x, y))
            assert len(green) > 12000, "Right-face SurfaceGui did not render"
            assert 175 < min(x for x, _ in green) < 190
            assert 310 < max(x for x, _ in green) < 325
            assert 170 < min(y for _, y in green) < 185
            assert 260 < max(y for _, y in green) < 275

    with tempfile.TemporaryDirectory(prefix="rhr-surface-top-test-") as directory:
        output = Path(directory) / "surface-top.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_top.rbxmx"),
                "--viewport", "500x350", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            green = []
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if pixel[1] > 150 and pixel[0] < 100 and pixel[2] < 150:
                        green.append((x, y))
            assert len(green) > 12000, "Top-face SurfaceGui did not render"
            assert 175 < min(x for x, _ in green) < 190
            assert 310 < max(x for x, _ in green) < 325
            assert 120 < min(y for _, y in green) < 135
            assert 215 < max(y for _, y in green) < 230

    with tempfile.TemporaryDirectory(prefix="rhr-surface-left-test-") as directory:
        output = Path(directory) / "surface-left.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_left.rbxmx"),
                "--viewport", "500x350", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            green = []
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if pixel[1] > 150 and pixel[0] < 100 and pixel[2] < 150:
                        green.append((x, y))
            assert len(green) > 12000, "Left-face SurfaceGui did not render"
            assert 175 < min(x for x, _ in green) < 190
            assert 310 < max(x for x, _ in green) < 325
            assert 170 < min(y for _, y in green) < 185
            assert 260 < max(y for _, y in green) < 275

    with tempfile.TemporaryDirectory(prefix="rhr-surface-bottom-test-") as directory:
        output = Path(directory) / "surface-bottom.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_bottom.rbxmx"),
                "--viewport", "500x350", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            green = []
            for y in range(image.height):
                for x in range(image.width):
                    pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                    if pixel[1] > 150 and pixel[0] < 100 and pixel[2] < 150:
                        green.append((x, y))
            assert len(green) > 12000, "Bottom-face SurfaceGui did not render"
            assert 175 < min(x for x, _ in green) < 190
            assert 310 < max(x for x, _ in green) < 325
            assert 120 < min(y for _, y in green) < 135
            assert 215 < max(y for _, y in green) < 230

    with tempfile.TemporaryDirectory(prefix="rhr-surface-occlusion-test-") as directory:
        output = Path(directory) / "surface-occlusion.png"
        subprocess.run(
            [
                str(ROOT / "bin/rhr"), "scene",
                str(ROOT / "tests/fixtures/surface_occlusion.rbxmx"),
                "--viewport", "500x350", "--out", str(output),
            ], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        with Image.open(output).convert("RGB") as image:
            red = 0
            green = 0
            yellow = 0
            for y in range(image.height):
                for x in range(image.width):
                    r, g, b = cast(tuple[int, int, int], image.getpixel((x, y)))
                    red += int(r > 150 and g < 100 and b < 100)
                    green += int(g > 150 and r < 100 and b < 100)
                    yellow += int(r > 180 and g > 120 and b < 100)
            assert red == 0, "occluded non-AlwaysOnTop SurfaceGui remained visible"
            assert green > 7000, "unoccluded non-AlwaysOnTop SurfaceGui did not render"
            assert yellow > 7000, "AlwaysOnTop SurfaceGui did not survive occlusion"
    print("surface gui: ok")


if __name__ == "__main__":
    main()
