#!/usr/bin/env python3
"""Many shadow-casting local lights must not make textured parts vanish.

Each shadow-casting light takes one of a shader's 16 texture units. A shop with 17
SpotLights (Shadows on) and textured materials went past the limit: the browser
refused those shaders and every Wood, Plastic and Fabric part vanished, while the
output reported nothing wrong. Now only the most relevant few cast shadows (a note
says so), and a shader the browser refuses is reported instead of silent.
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
LIGHTS = 20


def cframe(x: float, y: float, z: float) -> dict:
    return {"_t": "CFrame", "X": x, "Y": y, "Z": z,
            "R00": 1, "R01": 0, "R02": 0, "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1}


def part(name: str, position: tuple, size: tuple, material: str, children: list | None = None) -> dict:
    return {"className": "Part", "name": name, "children": children or [], "props": {
        "CFrame": cframe(*position), "Size": {"_t": "Vector3", "X": size[0], "Y": size[1], "Z": size[2]},
        "Color": {"_t": "Color3", "R": 0.9, "G": 0.1, "B": 0.1}, "Transparency": 0, "CastShadow": True,
        "Material": {"_t": "EnumItem", "name": material, "value": 0},
        "Shape": {"_t": "EnumItem", "name": "Block", "value": 1}}}


def scene_ir() -> dict:
    lamps = []
    for i in range(LIGHTS):
        light = {"className": "SpotLight", "name": "Spot", "children": [], "props": {
            "Brightness": 1, "Range": 20, "Angle": 60, "Shadows": True,
            "Color": {"_t": "Color3", "R": 1, "G": 1, "B": 1},
            "Face": {"_t": "EnumItem", "name": "Bottom", "value": 4}}}
        lamps.append(part(f"Lamp{i}", ((i % 5) * 4 - 8, 10, (i // 5) * 4 - 6), (0.5, 0.5, 0.5), "Plastic", [light]))
    return {"sourcePath": "many-shadows", "roots": [
        {"className": "Lighting", "name": "Lighting", "children": [], "props": {"ClockTime": 12}},
        {"className": "Workspace", "name": "Workspace", "props": {}, "children": [
            part("Floor", (0, 0, 0), (40, 1, 40), "Wood"),
            part("Block", (0, 2, 0), (6, 4, 6), "Wood"),
            *lamps,
        ]},
    ]}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-shadows-") as directory:
        tmp = Path(directory)
        source = tmp / "many-shadows.json"
        source.write_text(json.dumps(scene_ir()), encoding="utf-8")
        out = tmp / "out.png"
        proc = subprocess.run([*RHR, "scene", str(source), "--camera=0,14,-26", "--look-at=0,1,0", "--fov", "60",
                               "--viewport", "400x300", "--out", str(out), "--offline"],
                              cwd=ROOT, capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stderr
        assert "could not draw" not in proc.stderr, proc.stderr
        assert "cast shadows;" in proc.stderr, f"no note about the lights left without shadows\n{proc.stderr}"
        with Image.open(out).convert("RGB") as image:
            r, g, b = image.getpixel((200, 170))  # the red Wood block
        assert r > 60 and r > 1.5 * g and r > 1.5 * b, f"the Wood block is not drawn (pixel {r},{g},{b})"
    print(f"many shadows: {LIGHTS} shadow-casting SpotLights, textured parts still drawn")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
