#!/usr/bin/env python3
"""Cached Roblox MeshPart geometry: v1/v2/v4 decode and fallback contract."""

from __future__ import annotations

import sys
import json
import struct
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
BG = (32, 36, 43)

VERTICES = [
    (-1.0, -1.0, -0.5),
    (1.0, -1.0, -0.5),
    (0.0, 1.0, -0.5),
    (0.0, -0.25, 1.5),
]
FACES = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]


def _normal(_p):
    return (0.0, 0.0, 1.0)


def mesh_v1() -> bytes:
    chunks = ["version 1.00\r\n", f"{len(FACES)}\r\n"]
    for face in FACES:
        for index in face:
            p = VERTICES[index]
            n = _normal(p)
            uv = (0.0, 0.0, 0.0)
            chunks.append(f"[{p[0]},{p[1]},{p[2]}]")
            chunks.append(f"[{n[0]},{n[1]},{n[2]}]")
            chunks.append(f"[{uv[0]},{uv[1]},{uv[2]}]")
    return "".join(chunks).encode()


def vertex_record(p) -> bytes:
    # 8 floats (position, normal, uv), 4 signed tangent bytes, 4 RGBA bytes.
    return struct.pack(
        "<8f4b4B",
        p[0], p[1], p[2],
        0.0, 0.0, 1.0,
        0.0, 0.0,
        0, 0, 0, 0,
        255, 255, 255, 255,
    )


def mesh_v2() -> bytes:
    header = struct.pack("<HBBII", 12, 40, 12, len(VERTICES), len(FACES))
    vertices = b"".join(vertex_record(p) for p in VERTICES)
    faces = b"".join(struct.pack("<III", *face) for face in FACES)
    return b"version 2.00\n" + header + vertices + faces


def mesh_v3() -> bytes:
    # v3: 16-byte header with LOD stride/count before 32-bit vertex/face counts.
    header = struct.pack(
        "<HBBHHII",
        16, 40, 12,
        4, 1,
        len(VERTICES), len(FACES),
    )
    vertices = b"".join(vertex_record(p) for p in VERTICES)
    faces = b"".join(struct.pack("<III", *face) for face in FACES)
    lods = struct.pack("<II", 0, len(FACES))
    return b"version 3.00\n" + header + vertices + faces + lods


def mesh_v4() -> bytes:
    # v4.01: 24-byte header, one LOD span after face data.
    header = struct.pack(
        "<HHIIHHIHBB",
        24, 0,
        len(VERTICES), len(FACES),
        2, 0,
        0,
        0,
        1, 0,
    )
    vertices = b"".join(vertex_record(p) for p in VERTICES)
    faces = b"".join(struct.pack("<III", *face) for face in FACES)
    lods = struct.pack("<II", 0, len(FACES))
    return b"version 4.01\n" + header + vertices + faces + lods


def mesh_v5() -> bytes:
    # v5 extends the v4 header with two FACS fields; static vertex/face placement
    # remains after the declared header size.
    header = struct.pack(
        "<HHIIHHIHBBII",
        32, 0,
        len(VERTICES), len(FACES),
        2, 0,
        0,
        0,
        1, 0,
        0, 0,
    )
    vertices = b"".join(vertex_record(p) for p in VERTICES)
    faces = b"".join(struct.pack("<III", *face) for face in FACES)
    lods = struct.pack("<II", 0, len(FACES))
    return b"version 5.00\n" + header + vertices + faces + lods


def ir(asset_id: str) -> dict:
    return {
        "sourcePath": "meshpart-test",
        "roots": [{
            "className": "Workspace",
            "name": "Workspace",
            "props": {},
            "children": [{
                "className": "MeshPart",
                "name": "AsymmetricMesh",
                "props": {
                    "CFrame": {
                        "_t": "CFrame",
                        "X": 0, "Y": 0, "Z": 0,
                        "R00": 1, "R01": 0, "R02": 0,
                        "R10": 0, "R11": 1, "R12": 0,
                        "R20": 0, "R21": 0, "R22": 1,
                    },
                    "Size": {"_t": "Vector3", "X": 7, "Y": 5, "Z": 4},
                    "Color": {"_t": "Color3", "R": 0.9, "G": 0.25, "B": 0.12},
                    "Transparency": 0,
                    "Reflectance": 0,
                    "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
                    "CastShadow": False,
                    "MeshId": f"rbxassetid://{asset_id}",
                },
                "children": [],
            }],
        }],
    }


def special_ir(asset_id: str) -> dict:
    data = ir(asset_id)
    holder = data["roots"][0]["children"][0]
    holder["className"] = "Part"
    holder["name"] = "LegacyHolder"
    holder["props"]["Size"] = {"_t": "Vector3", "X": 0.2, "Y": 0.2, "Z": 0.2}
    holder["props"].pop("MeshId", None)
    holder["props"]["Shape"] = {"_t": "EnumItem", "name": "Block", "value": 1}
    holder["children"] = [{
        "className": "SpecialMesh",
        "name": "Mesh",
        "props": {
            "MeshType": {"_t": "EnumItem", "name": "FileMesh", "value": 5},
            "MeshId": f"rbxassetid://{asset_id}",
            "Scale": {"_t": "Vector3", "X": 2, "Y": 2, "Z": 2},
            "Offset": {"_t": "Vector3", "X": 0, "Y": 0, "Z": 0},
        },
        "children": [],
    }]
    return data


def render(src: Path, mesh_dir: Path | None, out: Path) -> None:
    args = [
        *RHR, "scene", str(src),
        "--viewport", "360x280",
        "--camera", "0,0,-14",
        "--look-at", "0,0,0",
        "--fov", "42",
        "--out", str(out),
    ]
    if mesh_dir is not None:
        args.extend(["--mesh-dir", str(mesh_dir)])
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def mean_delta(a: Path, b: Path) -> float:
    with Image.open(a).convert("RGB") as first, Image.open(b).convert("RGB") as second:
        return sum(ImageStat.Stat(ImageChops.difference(first, second)).mean) / 3


def silhouette(path: Path) -> set[tuple[int, int]]:
    with Image.open(path).convert("RGB") as image:
        points = set()
        for y in range(image.height):
            for x in range(image.width):
                r, g, b = image.getpixel((x, y))
                if abs(r - BG[0]) + abs(g - BG[1]) + abs(b - BG[2]) > 25:
                    points.add((x, y))
        return points


def iou(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> float:
    return len(a & b) / max(1, len(a | b))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-meshpart-") as directory:
        tmp = Path(directory)
        meshes = tmp / "meshes"
        meshes.mkdir()
        payloads = {
            "1001": mesh_v1(),
            "1002": mesh_v2(),
            "1003": mesh_v3(),
            "1004": mesh_v4(),
            "1005": mesh_v5(),
        }
        images = {}
        for asset_id, payload in payloads.items():
            (meshes / f"{asset_id}.mesh").write_bytes(payload)
            src = tmp / f"{asset_id}.json"
            src.write_text(json.dumps(ir(asset_id)))
            out = tmp / f"{asset_id}.png"
            render(src, meshes, out)
            images[asset_id] = out

        missing_src = tmp / "missing.json"
        missing_src.write_text(json.dumps(ir("1999")))
        missing = tmp / "missing.png"
        render(missing_src, meshes, missing)

        v1 = silhouette(images["1001"])
        v2 = silhouette(images["1002"])
        v3 = silhouette(images["1003"])
        v4 = silhouette(images["1004"])
        v5 = silhouette(images["1005"])
        missing_shape = silhouette(missing)

        assert len(v1) > 1500
        assert iou(v1, v2) > 0.98, iou(v1, v2)
        assert iou(v1, v3) > 0.98, iou(v1, v3)
        assert iou(v1, v4) > 0.98, iou(v1, v4)
        assert iou(v1, v5) > 0.98, iou(v1, v5)
        assert iou(v1, missing_shape) < 0.75, iou(v1, missing_shape)
        delta = mean_delta(images["1002"], missing)
        assert delta > 3.0, delta

        special_src = tmp / "special.json"
        special_src.write_text(json.dumps(special_ir("1002")))
        special_out = tmp / "special.png"
        render(special_src, meshes, special_out)

        special_missing_src = tmp / "special-missing.json"
        special_missing_src.write_text(json.dumps(special_ir("1999")))
        special_missing = tmp / "special-missing.png"
        render(special_missing_src, meshes, special_missing)
        special_delta = mean_delta(special_out, special_missing)
        assert special_delta > 3.0, special_delta
        assert len(silhouette(special_out)) > len(silhouette(special_missing)) * 10

        dump_proc = subprocess.run(
            [*RHR, "scene-dump", str(tmp / "1002.json"), "--mesh-dir", str(meshes)],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        assert dump_proc.returncode == 0, dump_proc.stderr
        dump = json.loads(dump_proc.stdout)
        assert dump["fallbacks"] == {}, dump["fallbacks"]
        assert dump["parts"][0]["geometry"] == "mesh-asset"
        assert dump["meshReferences"] == [{
            "path": "Workspace/AsymmetricMesh",
            "class": "MeshPart",
            "property": "MeshId",
            "uri": "rbxassetid://1002",
            "assetId": "1002",
            "available": True,
        }]

        special_dump_proc = subprocess.run(
            [*RHR, "scene-dump", str(special_src), "--mesh-dir", str(meshes)],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        assert special_dump_proc.returncode == 0, special_dump_proc.stderr
        special_dump = json.loads(special_dump_proc.stdout)
        assert special_dump["unsupportedVisualClasses"] == {}
        assert special_dump["specialMeshes"][0]["supported"] is True

    print(
        "scene meshpart: "
        f"v1/v2={iou(v1, v2):.3f}, v1/v3={iou(v1, v3):.3f}, "
        f"v1/v4={iou(v1, v4):.3f}, v1/v5={iou(v1, v5):.3f}, "
        f"mesh/box IoU={iou(v1, missing_shape):.3f}, delta={delta:.2f}, "
        f"FileMesh delta={special_delta:.2f}"
    )


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
