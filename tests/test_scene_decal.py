#!/usr/bin/env python3
"""Decals use local asset IDs and missing textures are reported, not hidden."""

from __future__ import annotations

import sys
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
ASSETS = ROOT / "tests/fixtures/assets"


def write_ir(path: Path, texture_id: str) -> None:
    path.write_text(json.dumps({
        "sourcePath": "decal-test",
        "roots": [{
            "className": "Workspace",
            "name": "Workspace",
            "props": {},
            "children": [{
                "className": "Part",
                "name": "Sign",
                "props": {
                    "CFrame": {
                        "_t": "CFrame",
                        "X": 0, "Y": 0, "Z": 0,
                        "R00": 1, "R01": 0, "R02": 0,
                        "R10": 0, "R11": 1, "R12": 0,
                        "R20": 0, "R21": 0, "R22": 1,
                    },
                    "Size": {"_t": "Vector3", "X": 8, "Y": 6, "Z": 1},
                    "Color": {"_t": "Color3", "R": 0.8, "G": 0.8, "B": 0.8},
                    "Transparency": 0,
                    "Reflectance": 0,
                    "CastShadow": True,
                    "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
                    "Shape": {"_t": "EnumItem", "name": "Block", "value": 1},
                },
                "children": [{
                    "className": "Decal",
                    "name": "Logo",
                    "props": {
                        "Texture": f"rbxassetid://{texture_id}",
                        "Face": {"_t": "EnumItem", "name": "Front", "value": 0},
                        "Color3": {"_t": "Color3", "R": 1, "G": 1, "B": 1},
                        "Transparency": 0,
                    },
                    "children": [],
                }],
            }],
        }],
    }))


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def color_counts(path: Path) -> tuple[int, int]:
    red = 0
    blue = 0
    with Image.open(path).convert("RGB") as image:
        for r, g, b in image.get_flattened_data():
            if r > 140 and r > g * 1.5 and r > b * 1.5:
                red += 1
            if b > 140 and b > r * 1.5 and b > g * 1.5:
                blue += 1
    return red, blue


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-decal-") as directory:
        tmp = Path(directory)
        good = tmp / "good.json"
        write_ir(good, "900000001")
        out = tmp / "decal.png"
        proc = run(
            "scene", str(good),
            "--viewport", "320x240",
            "--view", "back",
            "--texture-dir", str(ASSETS),
            "--out", str(out),
        )
        assert proc.returncode == 0, proc.stderr
        assert "missing-assets=0" in proc.stderr, proc.stderr
        red, blue = color_counts(out)
        assert red > 1000 and blue > 1000, (red, blue)

        proc = run("scene-dump", str(good), "--texture-dir", str(ASSETS))
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data["unsupportedVisualClasses"] == {}
        assert data["assetReferences"] == [{
            "assetId": "900000001",
            "available": True,
            "class": "Decal",
            "path": "Workspace/Sign/Logo",
            "property": "Texture",
            "uri": "rbxassetid://900000001",
        }]

        missing = tmp / "missing.json"
        write_ir(missing, "900000002")
        missing_out = tmp / "missing.png"
        proc = run(
            "scene", str(missing),
            "--viewport", "320x240",
            "--view", "back",
            "--texture-dir", str(ASSETS),
            "--coverage",
            "--out", str(missing_out),
        )
        assert proc.returncode == 0, proc.stderr
        assert "missing-assets=1" in proc.stderr, proc.stderr

    print(f"scene decal: red={red} blue={blue}, missing asset reported")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
