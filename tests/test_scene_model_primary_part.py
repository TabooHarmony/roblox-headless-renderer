#!/usr/bin/env python3
"""Visual contract for Model.Scale around Model.PrimaryPart."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests" / "fixtures" / "scene_model_primary_part.rbxmx"


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
        "--camera=4,0,24", "--look-at=4,0,0", "--fov=50", "--out", str(output),
    ])


def primary_part_expected(ir: dict) -> dict:
    expected = copy.deepcopy(ir)
    model = next(node for node in walk(expected["roots"][0]) if node.get("name") == "PrimaryAssembly")
    scale = float(model["props"]["Scale"])
    reference = model["props"].get("PrimaryPart")
    assert isinstance(reference, str) and reference
    primary_name = reference.split(".")[-1]
    parts = [node for node in walk(model) if node.get("className") == "Part"]
    primary = next(node for node in parts if node.get("name") == primary_name)
    pivot = primary["props"]["CFrame"]
    pivot_x = float(pivot["X"])
    pivot_y = float(pivot["Y"])
    pivot_z = float(pivot["Z"])

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
    with tempfile.TemporaryDirectory(prefix="rhr-scene-model-primary-part-") as directory:
        tmp = Path(directory)
        emitted = tmp / "primary-part.json"
        run([str(RHR), "ir", str(FIXTURE), "--out", str(emitted)])
        ir = json.loads(emitted.read_text())
        model = next(node for node in walk(ir["roots"][0]) if node.get("name") == "PrimaryAssembly")
        assert model["props"]["Scale"] == 1.5
        assert isinstance(model["props"].get("PrimaryPart"), str)

        actual = tmp / "actual.png"
        render(emitted, actual)
        actual_static = tmp / "actual-static.png"
        render(FIXTURE, actual_static)

        expected_ir = tmp / "expected.json"
        expected_ir.write_text(json.dumps(primary_part_expected(ir)))
        expected = tmp / "expected.png"
        render(expected_ir, expected)

        def changed_pixels(left: Path, right: Path) -> int:
            with Image.open(left) as left_image, Image.open(right) as right_image:
                diff = ImageChops.difference(left_image.convert("RGB"), right_image.convert("RGB"))
                return sum(
                    diff.getpixel((x, y)) != (0, 0, 0)
                    for y in range(diff.height)
                    for x in range(diff.width)
                )

        changed = changed_pixels(actual, expected)
        static_changed = changed_pixels(actual_static, expected)
        assert changed == 0, f"PrimaryPart pivot render differs from explicit transform: {changed} pixels"
        assert static_changed == 0, f"static-profile render differs from explicit transform: {static_changed} pixels"

        repeat = tmp / "actual-repeat.png"
        render(emitted, repeat)
        assert actual.read_bytes() == repeat.read_bytes(), "PrimaryPart pivot render is not deterministic"

        print(
            "scene model PrimaryPart pivot: "
            f"changed-vs-explicit={changed}, static-changed={static_changed}, "
            f"green={bbox(actual, 'green')}, "
            f"yellow={bbox(actual, 'yellow')}, deterministic"
        )


if __name__ == "__main__":
    main()
