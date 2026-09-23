#!/usr/bin/env python3
"""Decals and Textures lie on each part face the way Studio draws them.

Measured in Studio with the built-in Roblox logo as a Decal on each face of a
6-stud cube, viewed square-on from outside: the four side faces read upright. From
above and from below (screen-up = world -Z for both) the Top and Bottom images are
upside down. A tiled Texture on Top follows its Decal, and a positive OffsetStudsU
moves the image toward its own right. RHR used to draw the Top image upright.

The test image has a red top-left quarter and a blue top-right corner.

    python tests/test_decal_faces.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PIL import Image

from test_surface_gui_faces import centroid, face_center, is_blue, is_red, quadrant, render

ASSET_ID = "1000001"
UPRIGHT = (("left", "top"), ("right", "top"))
UPSIDE_DOWN = (("right", "bottom"), ("left", "bottom"))
CAMERAS = {
    "Front": "0,0,-14", "Back": "0,0,14", "Left": "-14,0,0", "Right": "14,0,0",
    "Top": "0,14,0.01", "Bottom": "0,-14,-0.01",
}
# (face, class, extra props, expected (red quadrant, blue quadrant))
CASES = [
    ("Front", "Decal", {}, UPRIGHT),
    ("Back", "Decal", {}, UPRIGHT),
    ("Left", "Decal", {}, UPRIGHT),
    ("Right", "Decal", {}, UPRIGHT),
    ("Top", "Decal", {}, UPSIDE_DOWN),
    ("Bottom", "Decal", {}, UPSIDE_DOWN),
    ("Top", "Texture", {"StudsPerTileU": 6, "StudsPerTileV": 6}, UPSIDE_DOWN),
    # A quarter tile along +U pushes the blue corner past the image's right edge, so
    # it wraps to the image's left (screen right, upside down); the other way it
    # would stay on the image's right.
    ("Top", "Texture", {"StudsPerTileU": 6, "StudsPerTileV": 6, "OffsetStudsU": 1.5}, None),
]


def marker_image(path: Path) -> None:
    image = Image.new("RGB", (64, 64), (128, 128, 128))
    image.paste((255, 0, 0), (0, 0, 32, 32))
    image.paste((0, 0, 255), (48, 0, 64, 16))
    image.save(path)


def scene(face: str, class_name: str, extra: dict) -> dict:
    props = {"Face": {"_t": "EnumItem", "enum": "Enum.NormalId", "name": face},
             "Texture": f"rbxassetid://{ASSET_ID}", **extra}
    part = {
        "className": "Part", "name": "Cube",
        "children": [{"className": class_name, "name": class_name, "props": props, "children": []}],
        "props": {
            "CFrame": {"_t": "CFrame", "X": 0, "Y": 0, "Z": 0, "R00": 1, "R01": 0, "R02": 0,
                       "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1},
            "Size": {"_t": "Vector3", "X": 6, "Y": 6, "Z": 6},
            "Color": {"_t": "Color3", "R": 0.16, "G": 0.55, "B": 0.16},
        },
    }
    return {"sourcePath": f"decal-{face}", "roots": [{"className": "Workspace", "name": "Workspace",
                                                      "props": {}, "children": [part]}]}


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="rhr-decal-faces-") as directory:
        tmp = Path(directory)
        textures = tmp / "textures"
        textures.mkdir()
        marker_image(textures / f"{ASSET_ID}.png")
        for number, (face, class_name, extra, expected) in enumerate(CASES):
            ir = tmp / f"case{number}.json"
            ir.write_text(json.dumps(scene(face, class_name, extra)), encoding="utf-8")
            image = render(ir, CAMERAS[face], tmp / f"case{number}.png", ["--texture-dir", str(textures)])
            center, red, blue = face_center(image), centroid(image, is_red), centroid(image, is_blue)
            label = f"{face} {class_name} {extra or ''}".strip()
            if not (center and red and blue):
                failures.append(f"{label}: markers missing (red={red}, blue={blue})")
                continue
            got = (quadrant(red, center), quadrant(blue, center))
            if expected is None:
                ok = got[1] == ("right", "bottom")
            else:
                ok = got == expected
            print(f"  {'ok  ' if ok else 'FAIL'} {label}: red {got[0]}, blue {got[1]}")
            if not ok:
                failures.append(f"{label}: red {got[0]} blue {got[1]}, expected {expected}")
    assert not failures, failures
    print("decal faces: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
