#!/usr/bin/env python3
"""Modern lighting: surfaces are lit by the sky only as far as they can see it.

Two floor tiles in a place with EnvironmentDiffuseScale 1 (as every current Roblox
template has) and no sun (Brightness 0), one open, one under a roof. The only thing that
can darken the covered tile is its sky visibility, which Roblox computes on a voxel
grid and RHR reproduces (scene.js buildSkyVisibility).

    python tests/test_scene_sky_light.py
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
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def part(name: str, pos: tuple[float, float, float], size: tuple[float, float, float]) -> dict:
    return {
        "className": "Part",
        "name": name,
        "props": {
            "CFrame": {"_t": "CFrame", "X": pos[0], "Y": pos[1], "Z": pos[2], "R00": 1, "R01": 0, "R02": 0,
                       "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1},
            "Size": {"_t": "Vector3", "X": size[0], "Y": size[1], "Z": size[2]},
            "Color": {"_t": "Color3", "R": 0.64, "G": 0.64, "B": 0.64},
            "Material": {"_t": "EnumItem", "enum": "Enum.Material", "name": "SmoothPlastic", "value": 272},
            "Shape": {"_t": "EnumItem", "enum": "Enum.PartType", "name": "Block", "value": 1},
        },
        "children": [],
    }


def main() -> int:
    parts = [
        part("OpenFloor", (-12, 0, 0), (12, 1, 12)),
        part("CoveredFloor", (12, 0, 0), (12, 1, 12)),
        part("Roof", (12, 9, 0), (14, 1, 14)),
        part("WallA", (5.5, 4.5, 0), (1, 9, 14)),
        part("WallB", (18.5, 4.5, 0), (1, 9, 14)),
    ]
    lighting = {"className": "Lighting", "name": "Lighting", "props": {
        "Brightness": 0, "ClockTime": 14, "EnvironmentDiffuseScale": 1, "EnvironmentSpecularScale": 1,
        "Ambient": {"_t": "Color3", "R": 0.2, "G": 0.2, "B": 0.2},
        "OutdoorAmbient": {"_t": "Color3", "R": 0.2, "G": 0.2, "B": 0.2},
    }, "children": []}
    with tempfile.TemporaryDirectory(prefix="rhr-skylight-") as directory:
        tmp = Path(directory)
        ir = tmp / "sky.json"
        ir.write_text(json.dumps({"sourcePath": "sky-light-test", "roots": [
            {"className": "Workspace", "name": "Workspace", "props": {}, "children": parts}, lighting]}))
        def floor_brightness(x: float) -> float | None:
            # From the open side (-Z), low, looking at the middle of one tile.
            out = tmp / f"sky{x}.png"
            proc = subprocess.run([*RHR, "scene", str(ir), "--out", str(out), "--viewport", "320x200",
                                   "--camera", f"{x},2.2,-9", "--look-at", f"{x},0.5,0", "--fov", "50",
                                   "--no-shadows", "--flat-materials"],
                                  cwd=ROOT, capture_output=True, text=True, timeout=300)
            check(f"scene renders (tile at x={x})", proc.returncode == 0, proc.stderr[-200:])
            if proc.returncode != 0:
                return None
            with Image.open(out).convert("RGB") as image:
                pixels = list(image.crop((130, 110, 190, 140)).get_flattened_data())
            return sum(sum(p) for p in pixels) / len(pixels) / 3

        open_floor = floor_brightness(-12)
        covered = floor_brightness(12)
        if open_floor is not None and covered is not None:
            check("a covered floor is darker than an open one (sky visibility)",
                  covered < open_floor - 15, f"covered {covered:.0f} vs open {open_floor:.0f}")
    print("scene sky light: ok" if not failures else f"scene sky light: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
