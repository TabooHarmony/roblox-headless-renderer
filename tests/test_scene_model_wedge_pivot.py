#!/usr/bin/env python3
"""Visual contract for a rotated WedgePart's default Model pivot."""

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
FIXTURE = ROOT / "tests" / "fixtures" / "scene_model_wedge_pivot.rbxmx"


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
        "--camera=3,0,24", "--look-at=3,0,0", "--fov=50", "--out", str(output),
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
    if part.get("className") in ("WedgePart", "CornerWedgePart"):
        local = []
        for x in (-sx, sx):
            for y in (-sy, sy):
                for z in (-sz, sz):
                    local_y = -sy if (
                        part.get("className") == "WedgePart" and x > 0
                    ) or (
                        part.get("className") == "CornerWedgePart" and y > 0 and (x > 0 or z > 0)
                    ) else y
                    local.append((x, local_y, z))
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


def wedge_expected(ir: dict) -> dict:
    expected = copy.deepcopy(ir)
    model = next(node for node in walk(expected["roots"][0]) if node.get("name") == "RotatedWedgeModel")
    parts = [node for node in walk(model) if node.get("className") in ("WedgePart", "CornerWedgePart", "Part")]
    scale = float(model["props"]["Scale"])
    pivot = bounds_center(parts)
    apply_scale(parts, scale, pivot)
    model["props"]["Scale"] = 1
    return expected


def pixel_at(image: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return cast(tuple[int, int, int], image.getpixel((x, y)))


def bbox(path: Path, kind: str) -> tuple[int, int, int, int]:
    predicates = {
        "green": lambda r, g, b: g > 140 and r < 130 and g > b * 1.08,
        "yellow": lambda r, g, b: r > 150 and g > 120 and b < 130,
        "blue": lambda r, g, b: b > 150 and b > r * 1.5 and b > g * 1.35,
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
    with tempfile.TemporaryDirectory(prefix="rhr-scene-model-wedge-pivot-") as directory:
        tmp = Path(directory)
        emitted = tmp / "wedge-pivot.json"
        run([str(RHR), "ir", str(FIXTURE), "--out", str(emitted)])
        ir = json.loads(emitted.read_text())
        model = next(node for node in walk(ir["roots"][0]) if node.get("name") == "RotatedWedgeModel")
        assert model["props"]["Scale"] == 1.5
        assert next(node for node in walk(model) if node.get("name") == "RotatedWedge")["className"] == "WedgePart"
        assert next(node for node in walk(model) if node.get("name") == "CornerBlue")["className"] == "CornerWedgePart"

        actual = tmp / "actual.png"
        render(emitted, actual)
        actual_static = tmp / "actual-static.png"
        render(FIXTURE, actual_static)

        expected_ir = tmp / "expected.json"
        expected_ir.write_text(json.dumps(wedge_expected(ir)))
        expected = tmp / "expected.png"
        render(expected_ir, expected)

        changed = changed_pixels(actual, expected)
        static_changed = changed_pixels(actual_static, expected)
        assert changed == 0, f"rotated wedge pivot differs from exact vertex bounds: {changed} pixels"
        assert static_changed == 0, f"static-profile wedge pivot differs: {static_changed} pixels"

        repeat = tmp / "actual-repeat.png"
        render(emitted, repeat)
        assert actual.read_bytes() == repeat.read_bytes(), "rotated wedge pivot is not deterministic"

        print(
            "scene rotated WedgePart pivot: "
            f"changed-vs-explicit={changed}, static-changed={static_changed}, "
            f"green={bbox(actual, 'green')}, yellow={bbox(actual, 'yellow')}, "
            f"blue={bbox(actual, 'blue')}, deterministic"
        )


if __name__ == "__main__":
    main()
