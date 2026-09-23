#!/usr/bin/env python3
"""Roblox Ball/Cylinder primitive proportions and axis conventions."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
BG = (32, 36, 43)


def part(shape: str, size: tuple[float, float, float]) -> dict:
    return {
        "className": "Part",
        "name": shape,
        "props": {
            "CFrame": {
                "_t": "CFrame",
                "X": 0, "Y": 0, "Z": 0,
                "R00": 1, "R01": 0, "R02": 0,
                "R10": 0, "R11": 1, "R12": 0,
                "R20": 0, "R21": 0, "R22": 1,
            },
            "Size": {"_t": "Vector3", "X": size[0], "Y": size[1], "Z": size[2]},
            "Color": {"_t": "Color3", "R": 0.85, "G": 0.85, "B": 0.85},
            "Transparency": 0,
            "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
            "Shape": {"_t": "EnumItem", "name": shape, "value": 0},
            "CastShadow": False,
        },
        "children": [],
    }


def render(shape: str, size: tuple[float, float, float], camera: str, look_at: str, out: Path) -> None:
    ir = out.with_suffix(".json")
    ir.write_text(json.dumps({
        "sourcePath": "primitive-proportion-test",
        "roots": [{
            "className": "Workspace",
            "name": "Workspace",
            "props": {},
            "children": [part(shape, size)],
        }],
    }))
    proc = subprocess.run(
        [
            str(RHR), "scene", str(ir),
            "--viewport", "320x240",
            "--camera", camera,
            "--look-at", look_at,
            "--fov", "45",
            "--out", str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def bbox(path: Path) -> tuple[int, int]:
    with Image.open(path).convert("RGB") as image:
        points = []
        for y in range(image.height):
            for x in range(image.width):
                r, g, b = image.getpixel((x, y))
                if abs(r - BG[0]) + abs(g - BG[1]) + abs(b - BG[2]) > 30:
                    points.append((x, y))
    assert len(points) > 300
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-primitives-") as directory:
        tmp = Path(directory)

        # A Roblox Ball follows all three Size dimensions; from the front,
        # Size 6x2x4 must look like a wide ellipse, not a 2x2 sphere.
        ball = tmp / "ball.png"
        render("Ball", (6, 2, 4), "0,0,-14", "0,0,0", ball)
        ball_w, ball_h = bbox(ball)
        ball_ratio = ball_w / ball_h
        assert 2.5 < ball_ratio < 3.5, (ball_w, ball_h, ball_ratio)

        # Roblox PartType.Cylinder's long axis is X. Looking along +X at a
        # Size 6x2x2 cylinder should show its 2x2 circular end cap.
        cylinder = tmp / "cylinder.png"
        render("Cylinder", (6, 2, 2), "14,0,0", "0,0,0", cylinder)
        cyl_w, cyl_h = bbox(cylinder)
        cyl_ratio = cyl_w / cyl_h
        assert 0.8 < cyl_ratio < 1.25, (cyl_w, cyl_h, cyl_ratio)

    print(
        f"scene primitives: ball={ball_w}x{ball_h} ratio={ball_ratio:.2f}, "
        f"cylinder-end={cyl_w}x{cyl_h} ratio={cyl_ratio:.2f}"
    )


if __name__ == "__main__":
    main()
