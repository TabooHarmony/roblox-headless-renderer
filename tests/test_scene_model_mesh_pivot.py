#!/usr/bin/env python3
"""Visual contract for a loaded MeshPart's non-centered geometry pivot."""

from __future__ import annotations

import copy
import json
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests" / "fixtures" / "scene_model_mesh_pivot.rbxmx"
VERTICES = [
    (-1.0, -1.0, -0.5),
    (1.0, -1.0, -0.5),
    (0.0, 1.0, -0.5),
    (0.0, -0.25, 4.5),
]
FACES = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]


def walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def mesh_payload() -> bytes:
    def record(point: tuple[float, float, float]) -> bytes:
        return struct.pack(
            "<8f4b4B",
            *point,
            0.0, 0.0, 1.0,
            0.0, 0.0,
            0, 0, 0, 0,
            255, 255, 255, 255,
        )

    header = struct.pack("<HBBII", 12, 40, 12, len(VERTICES), len(FACES))
    vertices = b"".join(record(point) for point in VERTICES)
    faces = b"".join(struct.pack("<III", *face) for face in FACES)
    return b"version 2.00\n" + header + vertices + faces


def run(command: list[str]) -> None:
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def render(source: Path, mesh_dir: Path, output: Path) -> None:
    run([
        str(RHR), "scene", str(source), "--mesh-dir", str(mesh_dir),
        "--viewport=640x360", "--camera=4,0,26", "--look-at=4,0,0", "--fov=50",
        "--out", str(output),
    ])


def cframe_point(cframe: dict, point: tuple[float, float, float]) -> tuple[float, float, float]:
    transformed = []
    for row, axis in enumerate(("X", "Y", "Z")):
        transformed.append(
            float(cframe[axis]) + sum(float(cframe[f"R{row}{column}"]) * point[column] for column in range(3))
        )
    return transformed[0], transformed[1], transformed[2]


def part_vertices(part: dict) -> list[tuple[float, float, float]]:
    size = part["props"]["Size"]
    sx, sy, sz = (float(size[key]) / 2 for key in ("X", "Y", "Z"))
    if part.get("className") == "MeshPart":
        mins = [min(point[index] for point in VERTICES) for index in range(3)]
        maxs = [max(point[index] for point in VERTICES) for index in range(3)]
        scales = [float(size[key]) / (maxs[index] - mins[index]) for index, key in enumerate(("X", "Y", "Z"))]
        local = [
            (point[0] * scales[0], point[1] * scales[1], point[2] * scales[2])
            for point in VERTICES
        ]
    else:
        local = [
            (x, y, z)
            for x in (-sx, sx)
            for y in (-sy, sy)
            for z in (-sz, sz)
        ]
    return [cframe_point(part["props"]["CFrame"], point) for point in local]


def bounds_center(parts: list[dict]) -> tuple[float, float, float]:
    points = [point for part in parts for point in part_vertices(part)]
    assert points
    return (
        (min(point[0] for point in points) + max(point[0] for point in points)) / 2,
        (min(point[1] for point in points) + max(point[1] for point in points)) / 2,
        (min(point[2] for point in points) + max(point[2] for point in points)) / 2,
    )


def apply_scale(parts: list[dict], scale: float, pivot: tuple[float, float, float]) -> None:
    for part in parts:
        cframe = part["props"]["CFrame"]
        size = part["props"]["Size"]
        position = [float(cframe[key]) for key in ("X", "Y", "Z")]
        for index, key in enumerate(("X", "Y", "Z")):
            cframe[key] = pivot[index] + scale * (position[index] - pivot[index])
            size[key] = float(size[key]) * scale


def expected_ir(ir: dict) -> dict:
    expected = copy.deepcopy(ir)
    model = next(node for node in walk(expected["roots"][0]) if node.get("name") == "MeshPivotModel")
    parts = [node for node in walk(model) if node.get("className") in ("MeshPart", "Part")]
    scale = float(model["props"]["Scale"])
    apply_scale(parts, scale, bounds_center(parts))
    model["props"]["Scale"] = 1
    return expected


def pixel_at(image: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return cast(tuple[int, int, int], image.getpixel((x, y)))


def bbox(path: Path, kind: str) -> tuple[int, int, int, int]:
    predicates = {
        "red": lambda r, g, b: r > 30 and r > g * 1.5 and r > b * 1.5,
        "yellow": lambda r, g, b: r > 150 and g > 120 and b < 130,
    }
    with Image.open(path).convert("RGB") as image:
        points = [
            (x, y)
            for y in range(image.height)
            for x in range(image.width)
            if predicates[kind](*pixel_at(image, x, y))
        ]
    assert len(points) > 50, (kind, len(points), path)
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def changed_pixels(left: Path, right: Path) -> int:
    with Image.open(left) as left_image, Image.open(right) as right_image:
        diff = ImageChops.difference(left_image.convert("RGB"), right_image.convert("RGB"))
        return sum(
            diff.getpixel((x, y)) != (0, 0, 0)
            for y in range(diff.height)
            for x in range(diff.width)
        )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-scene-model-mesh-pivot-") as directory:
        tmp = Path(directory)
        meshes = tmp / "meshes"
        meshes.mkdir()
        (meshes / "1101.mesh").write_bytes(mesh_payload())

        emitted = tmp / "mesh-pivot.json"
        run([str(RHR), "ir", str(FIXTURE), "--out", str(emitted)])
        ir = json.loads(emitted.read_text())
        model = next(node for node in walk(ir["roots"][0]) if node.get("name") == "MeshPivotModel")
        mesh = next(node for node in walk(model) if node.get("name") == "OffsetMesh")
        assert mesh["className"] == "MeshPart"
        assert mesh["props"]["MeshId"] == "rbxassetid://1101"

        actual = tmp / "actual.png"
        render(emitted, meshes, actual)
        static = tmp / "static.png"
        render(FIXTURE, meshes, static)

        expected_json = tmp / "expected.json"
        expected_json.write_text(json.dumps(expected_ir(ir)))
        expected = tmp / "expected.png"
        render(expected_json, meshes, expected)

        changed = changed_pixels(actual, expected)
        static_changed = changed_pixels(static, expected)
        assert changed == 0, f"loaded MeshPart pivot differs from exact mesh vertices: {changed} pixels"
        assert static_changed == 0, f"static-profile MeshPart pivot differs: {static_changed} pixels"
        repeat = tmp / "repeat.png"
        render(emitted, meshes, repeat)
        assert actual.read_bytes() == repeat.read_bytes(), "loaded MeshPart pivot is not deterministic"

        print(
            "scene MeshPart pivot: "
            f"changed-vs-explicit={changed}, static-changed={static_changed}, "
            f"red={bbox(actual, 'red')}, yellow={bbox(actual, 'yellow')}, deterministic"
        )


if __name__ == "__main__":
    main()
