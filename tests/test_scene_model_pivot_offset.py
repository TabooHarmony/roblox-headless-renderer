#!/usr/bin/env python3
"""Visual contract for Model.Scale around a PrimaryPart.PivotOffset."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests" / "fixtures" / "scene_model_pivot_offset.rbxmx"


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
        "--camera=3,0,24", "--look-at=3,0,0", "--fov=50", "--out", str(output),
    ])


def pivot_offset_expected(ir: dict) -> dict:
    expected = copy.deepcopy(ir)
    model = next(node for node in walk(expected["roots"][0]) if node.get("name") == "OffsetAssembly")
    scale = float(model["props"]["Scale"])
    reference = model["props"].get("PrimaryPart")
    assert isinstance(reference, str) and reference
    primary_name = reference.split(".")[-1]
    parts = [node for node in walk(model) if node.get("className") == "Part"]
    primary = next(node for node in parts if node.get("name") == primary_name)
    primary_cf = primary["props"]["CFrame"]
    offset = primary["props"]["PivotOffset"]

    # PivotOffset is local to the PrimaryPart. Transform its translation by
    # the part's rotation before applying the model's uniform scale.
    pivot_x = float(primary_cf["X"]) + sum(
        float(primary_cf[f"R0{i}"]) * float(offset[axis])
        for i, axis in enumerate(("X", "Y", "Z"))
    )
    pivot_y = float(primary_cf["Y"]) + sum(
        float(primary_cf[f"R1{i}"]) * float(offset[axis])
        for i, axis in enumerate(("X", "Y", "Z"))
    )
    pivot_z = float(primary_cf["Z"]) + sum(
        float(primary_cf[f"R2{i}"]) * float(offset[axis])
        for i, axis in enumerate(("X", "Y", "Z"))
    )

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
                pixel = image.getpixel((x, y))
                red, green, blue = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
                is_green = kind == "green" and green > 140 and red < 130 and green > blue * 1.08
                is_yellow = kind == "yellow" and red > 150 and green > 120 and blue < 130
                if is_green or is_yellow:
                    points.append((x, y))
    assert len(points) > 50, (kind, len(points), path)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
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
    with tempfile.TemporaryDirectory(prefix="rhr-scene-model-pivot-offset-") as directory:
        tmp = Path(directory)
        emitted = tmp / "pivot-offset.json"
        run([str(RHR), "ir", str(FIXTURE), "--out", str(emitted)])
        ir = json.loads(emitted.read_text())
        model = next(node for node in walk(ir["roots"][0]) if node.get("name") == "OffsetAssembly")
        assert model["props"]["Scale"] == 1.5
        assert isinstance(model["props"].get("PrimaryPart"), str)
        primary = next(node for node in walk(model) if node.get("name") == "OffsetGreen")
        assert primary["props"]["PivotOffset"]["X"] == 3

        actual = tmp / "actual.png"
        render(emitted, actual)
        actual_static = tmp / "actual-static.png"
        render(FIXTURE, actual_static)

        expected_ir = tmp / "expected.json"
        expected_ir.write_text(json.dumps(pivot_offset_expected(ir)))
        expected = tmp / "expected.png"
        render(expected_ir, expected)

        changed = changed_pixels(actual, expected)
        static_changed = changed_pixels(actual_static, expected)
        assert changed == 0, f"PivotOffset render differs from explicit transform: {changed} pixels"
        assert static_changed == 0, f"static-profile render differs from explicit transform: {static_changed} pixels"

        repeat = tmp / "actual-repeat.png"
        render(emitted, repeat)
        assert actual.read_bytes() == repeat.read_bytes(), "PivotOffset render is not deterministic"

        print(
            "scene model PrimaryPart PivotOffset: "
            f"changed-vs-explicit={changed}, static-changed={static_changed}, "
            f"green={bbox(actual, 'green')}, yellow={bbox(actual, 'yellow')}, deterministic"
        )


if __name__ == "__main__":
    main()
