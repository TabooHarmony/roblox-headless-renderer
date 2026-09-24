#!/usr/bin/env python3
"""Local six-face Sky cube map renders with stable Roblox face orientation."""

from __future__ import annotations

import sys
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
ASSETS = ROOT / "tests" / "fixtures" / "assets"


def sky_ir() -> dict:
    return {
        "sourcePath": "sky-test",
        "roots": [
            {
                "className": "Lighting",
                "name": "Lighting",
                "props": {"Brightness": 1, "GlobalShadows": False},
                "children": [{
                    "className": "Sky",
                    "name": "Sky",
                    "props": {
                        "SkyboxRt": "rbxassetid://900000011",
                        "SkyboxLf": "rbxassetid://900000012",
                        "SkyboxUp": "rbxassetid://900000013",
                        "SkyboxDn": "rbxassetid://900000014",
                        "SkyboxBk": "rbxassetid://900000015",
                        "SkyboxFt": "rbxassetid://900000016",
                        "SkyboxOrientation": {"_t": "Vector3", "X": 0, "Y": 0, "Z": 0},
                        "CelestialBodiesShown": True,
                        "StarCount": 3000,
                        "SunAngularSize": 11,
                        "MoonAngularSize": 11,
                    },
                    "children": [],
                }],
            },
            {"className": "Workspace", "name": "Workspace", "props": {}, "children": []},
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


def dominant(pixel: tuple[int, int, int], expected: str) -> None:
    r, g, b = pixel
    if expected == "red":
        assert r > 180 and r > g * 2 and r > b * 2, pixel
    elif expected == "green":
        assert g > 180 and g > r * 2 and g > b * 2, pixel
    elif expected == "blue":
        assert b > 180 and b > r * 2 and b > g * 2, pixel
    elif expected == "yellow":
        assert r > 180 and g > 180 and b < 100, pixel
    elif expected == "magenta":
        assert r > 180 and b > 180 and g < 100, pixel
    elif expected == "cyan":
        assert g > 180 and b > 180 and r < 100, pixel
    else:
        raise AssertionError(expected)


def main() -> None:
    # Checked in Studio with its default sky: looking toward +X shows the SkyboxLf
    # image, toward -X SkyboxRt; looking toward -Z shows SkyboxFt.
    directions = [
        ("+X shows SkyboxLf", "1,0,0", "green"),
        ("-X shows SkyboxRt", "-1,0,0", "red"),
        ("up", "0,1,0", "blue"),
        ("down", "0,-1,0", "yellow"),
        ("back", "0,0,1", "magenta"),
        ("front", "0,0,-1", "cyan"),
    ]

    with tempfile.TemporaryDirectory(prefix="rhr-sky-") as directory:
        tmp = Path(directory)
        src = tmp / "sky.json"
        src.write_text(json.dumps(sky_ir()))
        samples = {}

        for name, look_at, expected in directions:
            out = tmp / f"{name}.png"
            proc = run(
                "scene", str(src),
                "--viewport", "160x120",
                "--camera", "0,0,0",
                f"--look-at={look_at}",
                "--fov", "50",
                "--texture-dir", str(ASSETS),
                "--out", str(out),
            )
            assert proc.returncode == 0, proc.stderr
            with Image.open(out).convert("RGB") as image:
                sample = image.getpixel((image.width // 2, image.height // 2))
            samples[name] = sample

        for name, _look_at, expected in directions:
            dominant(samples[name], expected)

        proc = run("scene-dump", str(src), "--texture-dir", str(ASSETS))
        assert proc.returncode == 0, proc.stderr
        dump = json.loads(proc.stdout)
        assert "Sky" not in dump["unsupportedVisualClasses"]
        sky = dump["sky"]
        assert sky is not None and sky["complete"] is True
        assert len(sky["faces"]) == 6
        sky_refs = [item for item in dump["assetReferences"] if item["class"] == "Sky"]
        assert len(sky_refs) == 6 and all(item["available"] for item in sky_refs)

    summary = ", ".join(f"{name}={pixel}" for name, pixel in samples.items())
    print(f"scene sky: {summary}")


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
