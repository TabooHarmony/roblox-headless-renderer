#!/usr/bin/env python3
"""Visual contract for Model.Scale around the default bounding-box pivot."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests" / "fixtures" / "scene_model_default_pivot.rbxmx"


def walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def run(command: list[str]) -> None:
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def render(source: Path, output: Path) -> None:
    run(
        [
            str(RHR),
            "scene",
            str(source),
            "--viewport=480x360",
            "--camera=4,0,24",
            "--look-at=4,0,0",
            "--fov=50",
            "--out",
            str(output),
        ]
    )


def default_pivot_expected(ir: dict) -> dict:
    expected = copy.deepcopy(ir)
    model = next(node for node in walk(expected["roots"][0]) if node.get("name") == "AsymmetricAssembly")
    scale = float(model["props"]["Scale"])
    assert "WorldPivot" not in model["props"]

    min_x = float("inf")
    min_y = float("inf")
    min_z = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    max_z = float("-inf")
    parts = [node for node in walk(model) if node.get("className") == "Part"]
    for node in parts:
        props = node["props"]
        cframe = props["CFrame"]
        size = props["Size"]
        px = float(cframe["X"])
        py = float(cframe["Y"])
        pz = float(cframe["Z"])
        sx = float(size["X"])
        sy = float(size["Y"])
        sz = float(size["Z"])
        min_x = min(min_x, px - sx / 2)
        min_y = min(min_y, py - sy / 2)
        min_z = min(min_z, pz - sz / 2)
        max_x = max(max_x, px + sx / 2)
        max_y = max(max_y, py + sy / 2)
        max_z = max(max_z, pz + sz / 2)
    pivot_x = (min_x + max_x) / 2
    pivot_y = (min_y + max_y) / 2
    pivot_z = (min_z + max_z) / 2

    model["props"]["Scale"] = 1
    for node in parts:
        props = node["props"]
        cframe = props["CFrame"]
        size = props["Size"]
        cframe["X"] = pivot_x + scale * (float(cframe["X"]) - pivot_x)
        cframe["Y"] = pivot_y + scale * (float(cframe["Y"]) - pivot_y)
        cframe["Z"] = pivot_z + scale * (float(cframe["Z"]) - pivot_z)
        size["X"] = float(size["X"]) * scale
        size["Y"] = float(size["Y"]) * scale
        size["Z"] = float(size["Z"]) * scale
    return expected


def bbox(path: Path, kind: str) -> tuple[int, int, int, int]:
    with Image.open(path).convert("RGB") as image:
        points = []
        for y in range(image.height):
            for x in range(image.width):
                red, green, blue = image.getpixel((x, y))
                is_green = kind == "green" and green > 140 and red < 130 and green > blue * 1.08
                is_yellow = kind == "yellow" and red > 150 and green > 120 and blue < 130
                if is_green or is_yellow:
                    points.append((x, y))
    assert len(points) > 50, (kind, len(points), path)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-scene-model-default-pivot-") as directory:
        tmp = Path(directory)
        emitted = tmp / "default-pivot.json"
        run([str(RHR), "ir", str(FIXTURE), "--out", str(emitted)])
        ir = json.loads(emitted.read_text())
        model = next(node for node in walk(ir["roots"][0]) if node.get("name") == "AsymmetricAssembly")
        assert model["props"]["Scale"] == 1.5
        assert "WorldPivot" not in model["props"]

        actual = tmp / "actual.png"
        render(emitted, actual)

        expected_ir = tmp / "expected.json"
        expected_ir.write_text(json.dumps(default_pivot_expected(ir)))
        expected = tmp / "expected.png"
        render(expected_ir, expected)

        with Image.open(actual) as actual_image, Image.open(expected) as expected_image:
            diff = ImageChops.difference(actual_image.convert("RGB"), expected_image.convert("RGB"))
            changed = sum(
                diff.getpixel((x, y)) != (0, 0, 0)
                for y in range(diff.height)
                for x in range(diff.width)
            )
            assert changed == 0, f"default pivot render differs from explicit transform: {changed} pixels"

        repeat = tmp / "actual-repeat.png"
        render(emitted, repeat)
        assert actual.read_bytes() == repeat.read_bytes(), "default pivot render is not deterministic"

        print(
            "scene model default pivot: "
            f"changed-vs-explicit={changed}, green={bbox(actual, 'green')}, "
            f"yellow={bbox(actual, 'yellow')}, deterministic"
        )


if __name__ == "__main__":
    main()
