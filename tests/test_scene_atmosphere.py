#!/usr/bin/env python3
"""Atmosphere baseline: reported properties, background tint, and distance fog."""

from __future__ import annotations

import sys
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]


def color(r: float, g: float, b: float) -> dict:
    return {"_t": "Color3", "R": r, "G": g, "B": b}


def cframe(x: float, y: float, z: float) -> dict:
    return {
        "_t": "CFrame",
        "X": x, "Y": y, "Z": z,
        "R00": 1, "R01": 0, "R02": 0,
        "R10": 0, "R11": 1, "R12": 0,
        "R20": 0, "R21": 0, "R22": 1,
    }


def part(name: str, x: float, z: float, rgb: tuple[float, float, float]) -> dict:
    return {
        "className": "Part",
        "name": name,
        "props": {
            "CFrame": cframe(x, 1.5, z),
            "Size": {"_t": "Vector3", "X": 4, "Y": 4, "Z": 4},
            "Color": color(*rgb),
            "Transparency": 0,
            "Reflectance": 0,
            "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
            "Shape": {"_t": "EnumItem", "name": "Block", "value": 1},
            "CastShadow": False,
        },
        "children": [],
    }


def scene(density: float | None) -> dict:
    lighting_children = []
    if density is not None:
        lighting_children.append({
            "className": "Atmosphere",
            "name": "Atmosphere",
            "props": {
                "Color": color(0.72, 0.78, 0.92),
                "Decay": color(0.34, 0.42, 0.62),
                "Density": density,
                "Haze": 4.0,
                "Glare": 0.6,
                "Offset": -0.1,
            },
            "children": [],
        })
    return {
        "sourcePath": "atmosphere-test",
        "roots": [
            {
                "className": "Lighting",
                "name": "Lighting",
                "props": {
                    "Ambient": color(0.18, 0.18, 0.18),
                    "OutdoorAmbient": color(0.2, 0.22, 0.25),
                    "Brightness": 1.5,
                    "GlobalShadows": False,
                    "ClockTime": 15,
                    "GeographicLatitude": 35,
                },
                "children": lighting_children,
            },
            {
                "className": "Workspace",
                "name": "Workspace",
                "props": {},
                "children": [
                    part("Near", -4.2, 0, (0.95, 0.18, 0.12)),
                    part("Middle", 0, 8, (0.15, 0.85, 0.24)),
                    part("Far", 4.2, 16, (0.12, 0.28, 0.95)),
                ],
            },
        ],
    }


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*RHR, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def delta(a: Path, b: Path) -> float:
    with Image.open(a).convert("RGB") as first, Image.open(b).convert("RGB") as second:
        return sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / 3


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-atmosphere-") as directory:
        tmp = Path(directory)
        outputs = {}
        for name, density in (("none", None), ("thin", 0.0), ("dense", 0.65)):
            src = tmp / f"{name}.json"
            src.write_text(json.dumps(scene(density)))
            out = tmp / f"{name}.png"
            proc = run(
                "scene", str(src),
                "--viewport", "360x240",
                "--camera", "0,5,-20",
                "--look-at", "0,2,8",
                "--fov", "50",
                "--out", str(out),
            )
            assert proc.returncode == 0, proc.stderr
            outputs[name] = out

        tint_delta = delta(outputs["none"], outputs["thin"])
        fog_delta = delta(outputs["thin"], outputs["dense"])
        assert tint_delta > 20.0, tint_delta
        assert fog_delta > 1.0, fog_delta

        with Image.open(outputs["none"]).convert("RGB") as plain, Image.open(outputs["thin"]).convert("RGB") as tinted:
            # Without an Atmosphere a place shows Roblox's default sky (blue); the
            # Atmosphere tints that backdrop.
            sky = plain.getpixel((5, 5))
            assert sky[2] > sky[0] + 60, sky
            assert tinted.getpixel((5, 5)) != sky

        dense_ir = tmp / "dense.json"
        proc = run("scene-dump", str(dense_ir))
        assert proc.returncode == 0, proc.stderr
        dump = json.loads(proc.stdout)
        assert "Atmosphere" not in dump["unsupportedVisualClasses"]
        atmosphere = dump["atmosphere"]
        assert atmosphere is not None
        assert atmosphere["density"] == 0.65
        assert atmosphere["haze"] == 4.0
        assert atmosphere["glare"] == 0.6
        assert atmosphere["offset"] == -0.1

    print(f"scene atmosphere: tint delta={tint_delta:.2f}, fog delta={fog_delta:.2f}")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
