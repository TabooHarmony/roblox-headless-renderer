#!/usr/bin/env python3
"""WedgePart and CornerWedgePart slope the way Studio builds them.

Measured in Studio with raycasts onto the top surface: a WedgePart is low at its
front (local -Z) and full height at its back (+Z); a CornerWedgePart's peak stands
over its (+X, -Z) corner. RHR used to slope wedges along X, a 90-degree error.

The camera sits on +X looking at the origin, so screen-right is world -Z: the wedge's
high end (+Z) is on the left, the corner wedge's peak (-Z) on the right.

    python tests/test_scene_wedge_orientation.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]


def scene(class_name: str) -> dict:
    return {
        "sourcePath": "wedge-orientation",
        "roots": [{
            "className": "Workspace", "name": "Workspace", "props": {},
            "children": [{
                "className": class_name, "name": "Shape", "children": [],
                "props": {
                    "CFrame": {"_t": "CFrame", "X": 0, "Y": 0, "Z": 0,
                               "R00": 1, "R01": 0, "R02": 0, "R10": 0, "R11": 1, "R12": 0,
                               "R20": 0, "R21": 0, "R22": 1},
                    "Size": {"_t": "Vector3", "X": 4, "Y": 6, "Z": 8},
                    "Color": {"_t": "Color3", "R": 0.1, "G": 0.9, "B": 0.1},
                },
            }],
        }],
    }


def top_edges(png: Path) -> tuple[float, float]:
    """Mean top y of the green silhouette in the left and right thirds of its span."""
    with Image.open(png) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        columns = {}
        for x in range(width):
            for y in range(height):
                r, g, b = rgb.getpixel((x, y))
                if g > 120 and r < 110 and b < 110:
                    columns[x] = y
                    break
    xs = sorted(columns)
    assert len(xs) > 30, f"silhouette too small: {len(xs)} columns"
    third = (xs[-1] - xs[0]) / 3
    left = [columns[x] for x in xs if x < xs[0] + third]
    right = [columns[x] for x in xs if x > xs[-1] - third]
    return sum(left) / len(left), sum(right) / len(right)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-wedge-") as directory:
        tmp = Path(directory)
        results = {}
        for class_name in ("WedgePart", "CornerWedgePart"):
            source = tmp / f"{class_name}.json"
            out = tmp / f"{class_name}.png"
            source.write_text(json.dumps(scene(class_name)), encoding="utf-8")
            proc = subprocess.run(
                [*RHR, "scene", str(source), "--viewport", "320x240", "--camera", "20,0,0",
                 "--look-at", "0,0,0", "--fov", "50", "--out", str(out)],
                cwd=ROOT, capture_output=True, text=True, timeout=120,
            )
            assert proc.returncode == 0, proc.stderr
            results[class_name] = top_edges(out)
    wedge_left, wedge_right = results["WedgePart"]
    corner_left, corner_right = results["CornerWedgePart"]
    # Smaller y is higher on screen.
    assert wedge_left < wedge_right - 20, f"WedgePart must be high at +Z (screen left): {results['WedgePart']}"
    assert corner_right < corner_left - 20, f"CornerWedge peak must be at -Z (screen right): {results['CornerWedgePart']}"
    print(f"wedge orientation: WedgePart left/right tops {wedge_left:.0f}/{wedge_right:.0f}, "
          f"CornerWedgePart {corner_left:.0f}/{corner_right:.0f}")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
