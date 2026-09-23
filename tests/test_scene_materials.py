#!/usr/bin/env python3
"""Scene material approximations are visible, deterministic, and never fall back silently."""

from __future__ import annotations

import json
import statistics
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"


def part(name: str, x: float, material: str, *, reflectance: float = 0.0) -> dict:
    return {
        "className": "Part",
        "name": name,
        "props": {
            "CFrame": {
                "_t": "CFrame",
                "X": x, "Y": 0, "Z": 0,
                "R00": 1, "R01": 0, "R02": 0,
                "R10": 0, "R11": 1, "R12": 0,
                "R20": 0, "R21": 0, "R22": 1,
            },
            "Size": {"_t": "Vector3", "X": 3, "Y": 3, "Z": 3},
            "Color": {"_t": "Color3", "R": 0.45, "G": 0.45, "B": 0.45},
            "Transparency": 0,
            "Reflectance": reflectance,
            "CastShadow": True,
            "Material": {"_t": "EnumItem", "enum": "Enum.Material", "name": material, "value": 0},
            "Shape": {"_t": "EnumItem", "enum": "Enum.PartType", "name": "Block", "value": 1},
        },
        "children": [],
    }


def write_ir(path: Path, materials: list[tuple[str, float, str, float]]) -> None:
    children = [part(name, x, material, reflectance=reflectance) for name, x, material, reflectance in materials]
    path.write_text(json.dumps({
        "sourcePath": "material-test",
        "roots": [{
            "className": "Workspace",
            "name": "Workspace",
            "props": {},
            "children": children,
        }],
    }))


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(RHR), *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def foreground_brightness(path: Path, left_half: bool) -> float:
    with Image.open(path).convert("RGB") as image:
        x0, x1 = (0, image.width // 2) if left_half else (image.width // 2, image.width)
        values: list[float] = []
        for y in range(image.height):
            for x in range(x0, x1):
                r, g, b = image.getpixel((x, y))
                # Scene clear color is rgb(32,36,43). Exclude it and antialiasing near it.
                if max(abs(r - 32), abs(g - 36), abs(b - 43)) > 20:
                    values.append((r + g + b) / 3)
        assert values, f"no foreground pixels in {'left' if left_half else 'right'} half"
        return statistics.median(values)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-materials-") as directory:
        tmp = Path(directory)
        ir = tmp / "materials.json"
        write_ir(ir, [
            ("Plastic", -2.5, "Plastic", 0.0),
            ("Neon", 2.5, "Neon", 0.0),
        ])
        first = tmp / "first.png"
        second = tmp / "second.png"
        for output in (first, second):
            proc = run("scene", str(ir), "--viewport", "360x240", "--view", "front", "--out", str(output))
            assert proc.returncode == 0, proc.stderr
            assert "material-fallbacks=" not in proc.stderr, proc.stderr
        assert first.read_bytes() == second.read_bytes(), "material render is not deterministic"

        plastic = foreground_brightness(first, True)
        neon = foreground_brightness(first, False)
        assert neon > plastic + 25, (plastic, neon)

        unknown_ir = tmp / "unknown.json"
        write_ir(unknown_ir, [("Future", 0, "FutureMaterial", 0.6)])
        unknown_png = tmp / "unknown.png"
        proc = run("scene", str(unknown_ir), "--viewport", "240x180", "--view", "front", "--coverage", "--out", str(unknown_png))
        assert proc.returncode == 0, proc.stderr
        assert "material-fallbacks=1" in proc.stderr, proc.stderr

        proc = run("scene-dump", str(unknown_ir))
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data["materialFallbacks"] == {"FutureMaterial": 1}
        assert data["parts"][0]["reflectance"] == 0.6

    print(f"scene materials: plastic={plastic:.1f} neon={neon:.1f} deterministic")


if __name__ == "__main__":
    main()
