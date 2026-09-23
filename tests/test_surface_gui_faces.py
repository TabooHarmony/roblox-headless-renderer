#!/usr/bin/env python3
"""A SurfaceGui lies on each part face the way Studio draws it, and only from the front.

Measured in Studio (play mode) with a SurfaceGui on each face of a 6-stud cube: a red
frame in the GUI's top-left quarter and a small blue frame in its top-right corner.
Seen square-on from outside, the four side faces read upright and unmirrored. From
above (screen-up = world -Z) the Top face shows red bottom-left and blue top-left;
from below (screen-up = world -Z) the Bottom face shows the same. RHR used to mirror
Front and rotate Top/Bottom, and drew SurfaceGuis through the back of their part.

    python tests/test_surface_gui_faces.py
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

# face -> (camera, expected red quadrant, expected blue quadrant); quadrants are
# (horizontal, vertical) of the marker's centre relative to the face's centre.
VIEWS = {
    "Front": ("0,0,-14", ("left", "top"), ("right", "top")),
    "Back": ("0,0,14", ("left", "top"), ("right", "top")),
    "Left": ("-14,0,0", ("left", "top"), ("right", "top")),
    "Right": ("14,0,0", ("left", "top"), ("right", "top")),
    "Top": ("0,14,0.01", ("left", "bottom"), ("left", "top")),
    "Bottom": ("0,-14,-0.01", ("left", "bottom"), ("left", "top")),
}


def udim2(xs: float, ys: float, xo: float = 0, yo: float = 0) -> dict:
    return {"_t": "UDim2", "XS": xs, "XO": xo, "YS": ys, "YO": yo}


def frame(name: str, position: dict, size: dict, rgb: tuple[float, float, float]) -> dict:
    return {
        "className": "Frame", "name": name, "children": [],
        "props": {
            "Position": position, "Size": size, "BorderSizePixel": 0, "BackgroundTransparency": 0,
            "BackgroundColor3": {"_t": "Color3", "R": rgb[0], "G": rgb[1], "B": rgb[2]},
        },
    }


def scene(face: str) -> dict:
    gui = {
        "className": "SurfaceGui", "name": "SurfaceGui",
        "props": {
            "Face": {"_t": "EnumItem", "enum": "Enum.NormalId", "name": face},
            "SizingMode": {"_t": "EnumItem", "enum": "Enum.SurfaceGuiSizingMode", "name": "PixelsPerStud"},
            "PixelsPerStud": 20, "LightInfluence": 0, "Enabled": True,
        },
        "children": [
            frame("TopLeft", udim2(0, 0), udim2(0.5, 0.5), (1, 0, 0)),
            frame("TopRight", udim2(0.75, 0), udim2(0.25, 0.25), (0, 0, 1)),
        ],
    }
    part = {
        "className": "Part", "name": "Cube", "children": [gui],
        "props": {
            "CFrame": {"_t": "CFrame", "X": 0, "Y": 0, "Z": 0, "R00": 1, "R01": 0, "R02": 0,
                       "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1},
            "Size": {"_t": "Vector3", "X": 6, "Y": 6, "Z": 6},
            "Color": {"_t": "Color3", "R": 1, "G": 1, "B": 1},
        },
    }
    return {"sourcePath": f"surface-{face}", "roots": [{"className": "Workspace", "name": "Workspace",
                                                        "props": {}, "children": [part]}]}


def centroid(image: Image.Image, test) -> tuple[float, float] | None:
    xs, ys = [], []
    for y in range(image.height):
        for x in range(image.width):
            if test(image.getpixel((x, y))):
                xs.append(x)
                ys.append(y)
    if len(xs) < 20:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def is_red(p) -> bool:
    return p[0] > 180 and p[1] < 80 and p[2] < 80


def is_blue(p) -> bool:
    return p[2] > 180 and p[0] < 80 and p[1] < 80


def face_center(image: Image.Image) -> tuple[float, float] | None:
    """Centre of everything that is not the empty backdrop (the camera sees one face)."""
    backdrop = image.getpixel((0, 0))
    mask = Image.new("L", image.size)
    mask.putdata([255 if max(abs(a - b) for a, b in zip(p, backdrop)) > 20 else 0
                  for p in image.get_flattened_data()])
    bbox = mask.getbbox()
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2) if bbox else None


def quadrant(point: tuple[float, float], center: tuple[float, float]) -> tuple[str, str]:
    return ("left" if point[0] < center[0] else "right", "top" if point[1] < center[1] else "bottom")


def render(ir: Path, camera: str, out: Path, extra: list[str] | None = None) -> Image.Image:
    proc = subprocess.run(
        [*RHR, "scene", str(ir), "--viewport", "240x240", f"--camera={camera}", "--look-at", "0,0,0",
         "--fov", "50", "--out", str(out), *(extra or [])],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return Image.open(out).convert("RGB")


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="rhr-surface-faces-") as directory:
        tmp = Path(directory)
        for face, (camera, red_expected, blue_expected) in VIEWS.items():
            ir = tmp / f"{face}.json"
            ir.write_text(json.dumps(scene(face)), encoding="utf-8")
            image = render(ir, camera, tmp / f"{face}.png")
            center, red, blue = face_center(image), centroid(image, is_red), centroid(image, is_blue)
            if not (center and red and blue):
                failures.append(f"{face}: markers missing (red={red}, blue={blue})")
                continue
            got = (quadrant(red, center), quadrant(blue, center))
            ok = got == (red_expected, blue_expected)
            print(f"  {'ok  ' if ok else 'FAIL'} {face}: red {got[0]}, blue {got[1]}")
            if not ok:
                failures.append(f"{face}: red {got[0]} blue {got[1]}, expected {red_expected} {blue_expected}")

            # Seen from behind the part the face is hidden, and so is its GUI.
            behind = ",".join(str(-float(value)) for value in camera.split(","))
            back = render(ir, behind, tmp / f"{face}-behind.png")
            if centroid(back, is_red) or centroid(back, is_blue):
                failures.append(f"{face}: SurfaceGui drawn from behind its part")
    assert not failures, failures
    print("surface gui faces: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
