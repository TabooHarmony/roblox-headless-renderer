#!/usr/bin/env python3
"""Visual contract for nested Model.Scale composition."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests" / "fixtures" / "scene_model_nested.rbxmx"


def walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def run(command: list[str]) -> None:
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def render(source: Path, output: Path) -> None:
    run([
        str(RHR), "scene", str(source), "--viewport=480x360",
        "--camera=2,0,28", "--look-at=2,0,0", "--fov=50", "--out", str(output),
    ])


def pivot_of(model: dict) -> tuple[float, float, float]:
    points = []
    for node in walk(model):
        if node.get("className") != "Part":
            continue
        cframe = node["props"]["CFrame"]
        size = node["props"]["Size"]
        x, y, z = (float(cframe[key]) for key in ("X", "Y", "Z"))
        sx, sy, sz = (float(size[key]) for key in ("X", "Y", "Z"))
        points.extend([(x - sx / 2, y - sy / 2, z - sz / 2), (x + sx / 2, y + sy / 2, z + sz / 2)])
    assert points
    return tuple((min(point[index] for point in points) + max(point[index] for point in points)) / 2 for index in range(3))


def nested_expected(ir: dict) -> dict:
    expected = copy.deepcopy(ir)
    root = expected["roots"][0]
    outer = next(node for node in walk(root) if node.get("name") == "OuterAssembly")
    inner = next(node for node in walk(root) if node.get("name") == "InnerAssembly")

    inner_parts = [node for node in walk(inner) if node.get("className") == "Part"]
    inner_scale = float(inner["props"]["Scale"])
    inner_pivot = pivot_of(inner)
    for part in inner_parts:
        cframe = part["props"]["CFrame"]
        size = part["props"]["Size"]
        for index, key in enumerate(("X", "Y", "Z")):
            cframe[key] = inner_pivot[index] + inner_scale * (float(cframe[key]) - inner_pivot[index])
            size[key] = float(size[key]) * inner_scale
    inner["props"]["Scale"] = 1

    outer_parts = [node for node in walk(outer) if node.get("className") == "Part"]
    outer_scale = float(outer["props"]["Scale"])
    outer_pivot = pivot_of(outer)
    for part in outer_parts:
        cframe = part["props"]["CFrame"]
        size = part["props"]["Size"]
        for index, key in enumerate(("X", "Y", "Z")):
            cframe[key] = outer_pivot[index] + outer_scale * (float(cframe[key]) - outer_pivot[index])
            size[key] = float(size[key]) * outer_scale
    outer["props"]["Scale"] = 1
    return expected


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
            if predicates[kind](*image.getpixel((x, y)))
        ]
    assert len(points) > 50, (kind, len(points), path)
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-scene-model-nested-") as directory:
        tmp = Path(directory)
        emitted = tmp / "nested.json"
        run([str(RHR), "ir", str(FIXTURE), "--out", str(emitted)])
        ir = json.loads(emitted.read_text())
        outer = next(node for node in walk(ir["roots"][0]) if node.get("name") == "OuterAssembly")
        inner = next(node for node in walk(ir["roots"][0]) if node.get("name") == "InnerAssembly")
        assert outer["props"]["Scale"] == 1.25
        assert inner["props"]["Scale"] == 1.5

        actual = tmp / "actual.png"
        render(emitted, actual)

        expected_ir = tmp / "expected.json"
        expected_ir.write_text(json.dumps(nested_expected(ir)))
        expected = tmp / "expected.png"
        render(expected_ir, expected)

        with Image.open(actual) as actual_image, Image.open(expected) as expected_image:
            diff = ImageChops.difference(actual_image.convert("RGB"), expected_image.convert("RGB"))
            changed = sum(
                diff.getpixel((x, y)) != (0, 0, 0)
                for y in range(diff.height)
                for x in range(diff.width)
            )
            assert changed == 0, f"nested model render differs from explicit composition: {changed} pixels"

        repeat = tmp / "actual-repeat.png"
        render(emitted, repeat)
        assert actual.read_bytes() == repeat.read_bytes(), "nested model render is not deterministic"

        print(
            "scene nested model pivots: "
            f"changed-vs-explicit={changed}, green={bbox(actual, 'green')}, "
            f"blue={bbox(actual, 'blue')}, yellow={bbox(actual, 'yellow')}, deterministic"
        )


if __name__ == "__main__":
    main()
