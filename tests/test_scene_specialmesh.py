#!/usr/bin/env python3
"""Built-in SpecialMesh shapes render; FileMesh stays explicit unsupported."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"


def part(name: str, x: float, special: dict | None = None) -> dict:
    return {
        "className": "Part",
        "name": name,
        "props": {
            "CFrame": {
                "_t": "CFrame", "X": x, "Y": 0, "Z": 0,
                "R00": 1, "R01": 0, "R02": 0,
                "R10": 0, "R11": 1, "R12": 0,
                "R20": 0, "R21": 0, "R22": 1,
            },
            "Size": {"_t": "Vector3", "X": 4, "Y": 4, "Z": 4},
            "Color": {"_t": "Color3", "R": 0.8, "G": 0.3, "B": 0.15},
            "Transparency": 0,
            "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
            "Shape": {"_t": "EnumItem", "name": "Block", "value": 1},
        },
        "children": [special] if special else [],
    }


def special(name: str, mesh_type: str, mesh_id: str | None = None) -> dict:
    props = {
        "MeshType": {"_t": "EnumItem", "name": mesh_type, "value": 0},
        "Scale": {"_t": "Vector3", "X": 1, "Y": 1, "Z": 1},
        "Offset": {"_t": "Vector3", "X": 0, "Y": 0, "Z": 0},
    }
    if mesh_id:
        props["MeshId"] = mesh_id
    return {"className": "SpecialMesh", "name": name, "props": props, "children": []}


def render(ir: dict, path: Path) -> None:
    src = path.with_suffix(".json")
    src.write_text(json.dumps(ir))
    proc = subprocess.run(
        [str(RHR), "scene", str(src), "--viewport", "320x240",
         "--camera", "0,0,-16", "--look-at", "0,0,0", "--out", str(path)],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-specialmesh-") as directory:
        tmp = Path(directory)
        box_ir = {
            "sourcePath": "box",
            "roots": [{"className": "Workspace", "name": "Workspace", "props": {}, "children": [part("Shape", 0)]}],
        }
        sphere_ir = {
            "sourcePath": "sphere",
            "roots": [{"className": "Workspace", "name": "Workspace", "props": {}, "children": [part("Shape", 0, special("Mesh", "Sphere"))]}],
        }
        box = tmp / "box.png"
        sphere = tmp / "sphere.png"
        render(box_ir, box)
        render(sphere_ir, sphere)
        with Image.open(box).convert("RGB") as a, Image.open(sphere).convert("RGB") as b:
            delta = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
        assert delta > 0.5, delta

        mixed = {
            "sourcePath": "mixed",
            "roots": [{
                "className": "Workspace", "name": "Workspace", "props": {},
                "children": [
                    part("BuiltIn", -3, special("SphereMesh", "Sphere")),
                    part("External", 3, special("FileMesh", "FileMesh", "rbxassetid://123456")),
                ],
            }],
        }
        src = tmp / "mixed.json"
        src.write_text(json.dumps(mixed))
        proc = subprocess.run(
            [str(RHR), "scene-dump", str(src)],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        dump = json.loads(proc.stdout)
        assert dump["unsupportedVisualClasses"] == {"SpecialMesh:FileMesh": 1}
        assert [item["supported"] for item in dump["specialMeshes"]] == [True, False]

    print(f"scene specialmesh: sphere-vs-box delta={delta:.2f}, FileMesh remains explicit")


if __name__ == "__main__":
    main()
