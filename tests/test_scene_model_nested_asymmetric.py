#!/usr/bin/env python3
"""Visual contract for an asymmetric nested Model.Scale pivot."""

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
FIXTURE = ROOT / "tests" / "fixtures" / "scene_model_nested_asymmetric.rbxmx"


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
        "--camera=3,0,48", "--look-at=3,0,0", "--fov=50", "--out", str(output),
    ])


def parts_under(node: dict) -> list[dict]:
    return [child for child in walk(node) if child.get("className") == "Part"]


def bounds_center(parts: list[dict]) -> tuple[float, float, float]:
    bounds = []
    for part in parts:
        cframe = part["props"]["CFrame"]
        size = part["props"]["Size"]
        position = [float(cframe[key]) for key in ("X", "Y", "Z")]
        half = [float(size[key]) / 2 for key in ("X", "Y", "Z")]
        bounds.extend([[position[i] - half[i] for i in range(3)], [position[i] + half[i] for i in range(3)]])
    assert bounds
    return tuple((min(point[i] for point in bounds) + max(point[i] for point in bounds)) / 2 for i in range(3))


def apply_scale(parts: list[dict], scale: float, pivot: tuple[float, float, float]) -> None:
    for part in parts:
        cframe = part["props"]["CFrame"]
        size = part["props"]["Size"]
        for index, key in enumerate(("X", "Y", "Z")):
            cframe[key] = pivot[index] + scale * (float(cframe[key]) - pivot[index])
            size[key] = float(size[key]) * scale


def nested_asymmetric_expected(ir: dict) -> dict:
    expected = copy.deepcopy(ir)
    outer = next(node for node in walk(expected["roots"][0]) if node.get("name") == "OuterAsymmetric")
    inner = next(node for node in walk(outer) if node.get("name") == "InnerAsymmetric")
    inner_parts = parts_under(inner)
    all_parts = parts_under(outer)

    # Roblox computes the outer default bounding-box pivot from the geometry
    # after the nested model's existing scale has been applied.
    inner_pivot = bounds_center(inner_parts)
    apply_scale(inner_parts, float(inner["props"]["Scale"]), inner_pivot)
    inner["props"]["Scale"] = 1
    outer_pivot = bounds_center(all_parts)
    apply_scale(all_parts, float(outer["props"]["Scale"]), outer_pivot)
    outer["props"]["Scale"] = 1
    return expected


def pixel_at(image: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    return cast(tuple[int, int, int], image.getpixel((x, y)))


def bbox(path: Path, kind: str) -> tuple[int, int, int, int]:
    predicates = {
        "green": lambda r, g, b: g > 140 and r < 130 and g > b * 1.08,
        "blue": lambda r, g, b: b > 150 and b > r * 1.5 and b > g * 1.35,
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
    with tempfile.TemporaryDirectory(prefix="rhr-scene-model-nested-asymmetric-") as directory:
        tmp = Path(directory)
        emitted = tmp / "nested-asymmetric.json"
        run([str(RHR), "ir", str(FIXTURE), "--out", str(emitted)])
        ir = json.loads(emitted.read_text())
        outer = next(node for node in walk(ir["roots"][0]) if node.get("name") == "OuterAsymmetric")
        inner = next(node for node in walk(outer) if node.get("name") == "InnerAsymmetric")
        assert outer["props"]["Scale"] == 1.5
        assert inner["props"]["Scale"] == 2

        actual = tmp / "actual.png"
        render(emitted, actual)
        actual_static = tmp / "actual-static.png"
        render(FIXTURE, actual_static)

        expected_ir = tmp / "expected.json"
        expected_ir.write_text(json.dumps(nested_asymmetric_expected(ir)))
        expected = tmp / "expected.png"
        render(expected_ir, expected)

        changed = changed_pixels(actual, expected)
        static_changed = changed_pixels(actual_static, expected)
        assert changed == 0, f"asymmetric nested pivot differs from explicit transform: {changed} pixels"
        assert static_changed == 0, f"static-profile nested pivot differs from explicit transform: {static_changed} pixels"

        repeat = tmp / "actual-repeat.png"
        render(emitted, repeat)
        assert actual.read_bytes() == repeat.read_bytes(), "asymmetric nested pivot is not deterministic"

        print(
            "scene asymmetric nested pivots: "
            f"changed-vs-explicit={changed}, static-changed={static_changed}, "
            f"green={bbox(actual, 'green')}, blue={bbox(actual, 'blue')}, "
            f"yellow={bbox(actual, 'yellow')}, deterministic"
        )


if __name__ == "__main__":
    main()
