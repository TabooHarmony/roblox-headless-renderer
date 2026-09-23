#!/usr/bin/env python3
"""Visual contract for rotated non-box primitive Model pivots."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests" / "fixtures" / "scene_model_primitive_pivot.rbxmx"


def walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def run(command: list[str]) -> None:
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def render(source: Path, output: Path) -> None:
    run([
        str(RHR), "scene", str(source), "--viewport=640x360",
        "--camera=6,0,28", "--look-at=6,0,0", "--fov=50", "--out", str(output),
    ])


def shape_name(part: dict) -> str:
    value = part["props"].get("Shape", part["props"].get("shape"))
    return value.get("name", str(value)) if isinstance(value, dict) else str(value)


def cframe_point(cframe: dict, point: tuple[float, float, float]) -> tuple[float, float, float]:
    transformed = []
    for row, axis in enumerate(("X", "Y", "Z")):
        transformed.append(
            float(cframe[axis]) + sum(float(cframe[f"R{row}{column}"]) * point[column] for column in range(3))
        )
    return transformed[0], transformed[1], transformed[2]


def part_bounds(part: dict) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    size = part["props"]["Size"]
    half_x, half_y, half_z = (float(size[key]) / 2 for key in ("X", "Y", "Z"))
    shape = shape_name(part)
    cframe = part["props"]["CFrame"]
    if shape in ("Ball", "2"):
        extents = []
        for row in range(3):
            r0 = float(cframe[f"R{row}0"])
            r1 = float(cframe[f"R{row}1"])
            r2 = float(cframe[f"R{row}2"])
            extents.append((r0 * half_x) ** 2 + (r1 * half_y) ** 2 + (r2 * half_z) ** 2)
        extent = tuple(value ** 0.5 for value in extents)
        center = tuple(float(cframe[key]) for key in ("X", "Y", "Z"))
        return (
            (center[0] - extent[0], center[1] - extent[1], center[2] - extent[2]),
            (center[0] + extent[0], center[1] + extent[1], center[2] + extent[2]),
        )
    if shape in ("Cylinder", "3"):
        extent = []
        for row in range(3):
            axis = abs(float(cframe[f"R{row}0"])) * half_x
            radial = (
                float(cframe[f"R{row}1"]) * half_y
            ) ** 2 + (float(cframe[f"R{row}2"]) * half_z) ** 2
            extent.append(axis + radial ** 0.5)
        center = tuple(float(cframe[key]) for key in ("X", "Y", "Z"))
        return (
            (center[0] - extent[0], center[1] - extent[1], center[2] - extent[2]),
            (center[0] + extent[0], center[1] + extent[1], center[2] + extent[2]),
        )
    local = [
        (x, y, z)
        for x in (-half_x, half_x)
        for y in (-half_y, half_y)
        for z in (-half_z, half_z)
    ]
    world = [cframe_point(cframe, point) for point in local]
    return (
        (min(point[0] for point in world), min(point[1] for point in world), min(point[2] for point in world)),
        (max(point[0] for point in world), max(point[1] for point in world), max(point[2] for point in world)),
    )


def box_part_bounds(part: dict) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    size = part["props"]["Size"]
    half_x, half_y, half_z = (float(size[key]) / 2 for key in ("X", "Y", "Z"))
    cframe = part["props"]["CFrame"]
    local = [
        (x, y, z)
        for x in (-half_x, half_x)
        for y in (-half_y, half_y)
        for z in (-half_z, half_z)
    ]
    world = [cframe_point(cframe, point) for point in local]
    return (
        (min(point[0] for point in world), min(point[1] for point in world), min(point[2] for point in world)),
        (max(point[0] for point in world), max(point[1] for point in world), max(point[2] for point in world)),
    )


def bounds_center_for(parts: list[dict], bounds_function) -> tuple[float, float, float]:
    bounds = [bounds_function(part) for part in parts]
    return (
        (min(pair[0][0] for pair in bounds) + max(pair[1][0] for pair in bounds)) / 2,
        (min(pair[0][1] for pair in bounds) + max(pair[1][1] for pair in bounds)) / 2,
        (min(pair[0][2] for pair in bounds) + max(pair[1][2] for pair in bounds)) / 2,
    )


def bounds_center(parts: list[dict]) -> tuple[float, float, float]:
    return bounds_center_for(parts, part_bounds)


def apply_scale(parts: list[dict], scale: float, pivot: tuple[float, float, float]) -> None:
    for part in parts:
        cframe = part["props"]["CFrame"]
        size = part["props"]["Size"]
        position = [float(cframe[key]) for key in ("X", "Y", "Z")]
        for index, key in enumerate(("X", "Y", "Z")):
            cframe[key] = pivot[index] + scale * (position[index] - pivot[index])
            size[key] = float(size[key]) * scale


def expected_ir(ir: dict, bounds_function=part_bounds) -> dict:
    expected = copy.deepcopy(ir)
    model = next(node for node in walk(expected["roots"][0]) if node.get("name") == "PrimitivePivotModel")
    parts = [node for node in walk(model) if node.get("className") == "Part"]
    apply_scale(parts, float(model["props"]["Scale"]), bounds_center_for(parts, bounds_function))
    model["props"]["Scale"] = 1
    return expected


def pixel_at(image: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return cast(tuple[int, int, int], image.getpixel((x, y)))


def bbox(path: Path, kind: str) -> tuple[int, int, int, int]:
    predicates = {
        "green": lambda r, g, b: g > 100 and g > r * 1.45 and g > b * 1.15,
        "blue": lambda r, g, b: b > 100 and b > r * 1.3 and b > g * 1.15,
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
    with tempfile.TemporaryDirectory(prefix="rhr-scene-model-primitive-pivot-") as directory:
        tmp = Path(directory)
        emitted = tmp / "primitive-pivot.json"
        run([str(RHR), "ir", str(FIXTURE), "--out", str(emitted)])
        ir = json.loads(emitted.read_text())
        model = next(node for node in walk(ir["roots"][0]) if node.get("name") == "PrimitivePivotModel")
        assert model["props"]["Scale"] == 1.5
        assert shape_name(next(node for node in walk(model) if node.get("name") == "RotatedBall")) in ("Ball", "2")
        assert shape_name(next(node for node in walk(model) if node.get("name") == "RotatedCylinder")) in ("Cylinder", "2")

        actual = tmp / "actual.png"
        render(emitted, actual)
        static = tmp / "static.png"
        render(FIXTURE, static)
        expected_json = tmp / "expected.json"
        expected_json.write_text(json.dumps(expected_ir(ir)))
        expected = tmp / "expected.png"
        render(expected_json, expected)
        box_json = tmp / "box-pivot.json"
        box_json.write_text(json.dumps(expected_ir(ir, box_part_bounds)))
        box = tmp / "box-pivot.png"
        render(box_json, box)

        changed = changed_pixels(actual, expected)
        static_changed = changed_pixels(static, expected)
        box_changed = changed_pixels(box, expected)
        assert changed == 0, f"primitive pivot differs from analytic shape bounds: {changed} pixels"
        assert static_changed == 0, f"static-profile primitive pivot differs: {static_changed} pixels"
        assert box_changed > 100, f"fixture does not distinguish box bounds from analytic bounds: {box_changed} pixels"
        repeat = tmp / "repeat.png"
        render(emitted, repeat)
        assert actual.read_bytes() == repeat.read_bytes(), "primitive pivot is not deterministic"

        print(
            "scene non-box primitive pivots: "
            f"changed-vs-explicit={changed}, static-changed={static_changed}, box-changed={box_changed}, "
            f"green={bbox(actual, 'green')}, blue={bbox(actual, 'blue')}, "
            f"yellow={bbox(actual, 'yellow')}, deterministic"
        )


if __name__ == "__main__":
    main()
