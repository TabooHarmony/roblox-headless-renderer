#!/usr/bin/env python3
"""Part-parented Roblox local lights visibly affect static scene geometry."""

from __future__ import annotations

import sys
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]


def base_ir(light_class: str | None) -> dict:
    lamp_children = []
    if light_class:
        lamp_children.append({
            "className": light_class,
            "name": light_class,
            "props": {
                "Color": {"_t": "Color3", "R": 1, "G": 0.15, "B": 0.08},
                "Brightness": 5,
                "Range": 14,
                "Shadows": False,
                "Angle": 100 if light_class == "SurfaceLight" else 70,
                "Face": {"_t": "EnumItem", "name": "Back", "value": 0},
            },
            "children": [],
        })
    return {
        "sourcePath": "local-light-test",
        "roots": [
            {
                "className": "Lighting",
                "name": "Lighting",
                "props": {
                    "Ambient": {"_t": "Color3", "R": 0.01, "G": 0.01, "B": 0.01},
                    "OutdoorAmbient": {"_t": "Color3", "R": 0.01, "G": 0.01, "B": 0.01},
                    "Brightness": 0,
                    "GlobalShadows": False,
                    "ClockTime": 12,
                    "GeographicLatitude": 35,
                },
                "children": [],
            },
            {
                "className": "Workspace",
                "name": "Workspace",
                "props": {},
                "children": [
                    {
                        "className": "Part",
                        "name": "Target",
                        "props": {
                            "CFrame": {
                                "_t": "CFrame",
                                "X": 0, "Y": 0, "Z": 0,
                                "R00": 1, "R01": 0, "R02": 0,
                                "R10": 0, "R11": 1, "R12": 0,
                                "R20": 0, "R21": 0, "R22": 1,
                            },
                            "Size": {"_t": "Vector3", "X": 6, "Y": 6, "Z": 1},
                            "Color": {"_t": "Color3", "R": 0.75, "G": 0.75, "B": 0.75},
                            "Transparency": 0,
                            "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
                            "Shape": {"_t": "EnumItem", "name": "Block", "value": 1},
                            "CastShadow": True,
                        },
                        "children": [],
                    },
                    {
                        "className": "Part",
                        "name": "LampAnchor",
                        "props": {
                            "CFrame": {
                                "_t": "CFrame",
                                "X": 0, "Y": 0, "Z": -4,
                                "R00": 1, "R01": 0, "R02": 0,
                                "R10": 0, "R11": 1, "R12": 0,
                                "R20": 0, "R21": 0, "R22": 1,
                            },
                            "Size": {"_t": "Vector3", "X": 0.2, "Y": 0.2, "Z": 0.2},
                            "Color": {"_t": "Color3", "R": 0, "G": 0, "B": 0},
                            "Transparency": 1,
                            "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
                            "Shape": {"_t": "EnumItem", "name": "Block", "value": 1},
                            "CastShadow": False,
                        },
                        "children": lamp_children,
                    },
                ],
            },
        ],
    }


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*RHR, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def delta(a: Path, b: Path) -> float:
    with Image.open(a).convert("RGB") as first, Image.open(b).convert("RGB") as second:
        return sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / 3


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-local-lights-") as directory:
        tmp = Path(directory)
        dark_ir = tmp / "none.json"
        dark_ir.write_text(json.dumps(base_ir(None)))
        dark_png = tmp / "none.png"
        common = [
            "--viewport", "320x240",
            "--camera", "0,0,-14",
            "--look-at", "0,0,0",
        ]
        proc = run("scene", str(dark_ir), *common, "--out", str(dark_png))
        assert proc.returncode == 0, proc.stderr

        deltas = {}
        for light_class in ("PointLight", "SpotLight", "SurfaceLight"):
            ir = tmp / f"{light_class}.json"
            ir.write_text(json.dumps(base_ir(light_class)))
            out = tmp / f"{light_class}.png"
            proc = run("scene", str(ir), *common, "--out", str(out))
            assert proc.returncode == 0, proc.stderr
            deltas[light_class] = delta(dark_png, out)
            assert deltas[light_class] > 2.0, (light_class, deltas[light_class])

            proc = run("scene-dump", str(ir))
            assert proc.returncode == 0, proc.stderr
            dump = json.loads(proc.stdout)
            assert dump["unsupportedVisualClasses"] == {}
            assert len(dump["lights"]) == 1
            light = dump["lights"][0]
            assert light["class"] == light_class
            assert light["range"] == 14
            assert light["brightness"] == 5
            assert light["face"] == "Back"

        attachment_data = base_ir("PointLight")
        lamp = attachment_data["roots"][1]["children"][1]
        point = lamp["children"][0]
        lamp["children"] = [{
            "className": "Attachment",
            "name": "Socket",
            "props": {"Position": {"_t": "Vector3", "X": 0, "Y": 0, "Z": 0}},
            "children": [point],
        }]
        attachment_ir = tmp / "attachment.json"
        attachment_ir.write_text(json.dumps(attachment_data))
        attachment_png = tmp / "attachment.png"
        proc = run("scene", str(attachment_ir), *common, "--out", str(attachment_png))
        assert proc.returncode == 0, proc.stderr
        attachment_delta = delta(dark_png, attachment_png)
        assert attachment_delta > 2.0, attachment_delta

    print(
        "scene local lights: "
        + ", ".join(f"{name} delta={value:.2f}" for name, value in deltas.items())
        + f", attachment PointLight delta={attachment_delta:.2f}"
    )


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
