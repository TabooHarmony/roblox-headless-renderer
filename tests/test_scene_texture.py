#!/usr/bin/env python3
"""Texture repeats local assets over a face using StudsPerTileU/V."""

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


def write_ir(path: Path) -> None:
    path.write_text(json.dumps({
        "sourcePath": "texture-test",
        "roots": [{
            "className": "Workspace",
            "name": "Workspace",
            "props": {},
            "children": [{
                "className": "Part",
                "name": "Wall",
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
                    "className": "Texture",
                    "name": "Pattern",
                    "props": {
                        "Texture": "rbxassetid://900000001",
                        "Face": {"_t": "EnumItem", "name": "Front", "value": 0},
                        "Color3": {"_t": "Color3", "R": 1, "G": 1, "B": 1},
                        "Transparency": 0,
                        "StudsPerTileU": 2,
                        "StudsPerTileV": 6,
                        "OffsetStudsU": 0,
                        "OffsetStudsV": 0,
                    },
                    "children": [],
                }],
            }],
        }],
    }))


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def center_row_transitions(path: Path) -> int:
    with Image.open(path).convert("RGB") as image:
        y = image.height // 2
        classes: list[str] = []
        for x in range(image.width):
            r, g, b = image.getpixel((x, y))
            label = None
            if r > 140 and r > g * 1.5 and r > b * 1.5:
                label = "R"
            elif b > 140 and b > r * 1.5 and b > g * 1.5:
                label = "B"
            if label and (not classes or classes[-1] != label):
                classes.append(label)
        return max(0, len(classes) - 1)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-texture-") as directory:
        tmp = Path(directory)
        ir = tmp / "texture.json"
        write_ir(ir)
        out = tmp / "texture.png"
        proc = run(
            "scene", str(ir),
            "--viewport", "320x240",
            "--view", "back",
            "--texture-dir", str(ASSETS),
            "--out", str(out),
        )
        assert proc.returncode == 0, proc.stderr
        transitions = center_row_transitions(out)
        assert transitions >= 6, transitions

        proc = run("scene-dump", str(ir), "--texture-dir", str(ASSETS))
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data["unsupportedVisualClasses"] == {}
        assert len(data["assetReferences"]) == 1
        assert data["assetReferences"][0]["class"] == "Texture"
        assert data["assetReferences"][0]["available"] is True

    print(f"scene texture: center-row color transitions={transitions}")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
