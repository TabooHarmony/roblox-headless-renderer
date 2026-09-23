#!/usr/bin/env python3
"""Real emitted multi-view fixture for the basic 3D scene contract."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests" / "fixtures" / "scene_foundation.rbxmx"


def find_nodes(node: dict, class_name: str) -> list[dict]:
    found = [node] if node.get("className") == class_name else []
    for child in node.get("children", []):
        found.extend(find_nodes(child, class_name))
    return found


def color_kind(pixel: tuple[int, int, int]) -> str | None:
    red, green, blue = pixel
    if red > 150 and green < 130 and blue < 130 and red > green * 1.35:
        return "red"
    if green > 150 and blue > 150 and red < 130:
        return "cyan"
    if blue > 130 and red < 130 and blue > red * 1.35 and blue > green * 0.9:
        return "blue"
    if green > 140 and red < 130 and green > blue * 1.08:
        return "green"
    if red > 150 and green > 120 and blue < 130:
        return "yellow"
    if red > 100 and blue > 100 and green < 130 and red > green * 1.25:
        return "magenta"
    return None


def color_points(path: Path, kind: str) -> list[tuple[int, int]]:
    with Image.open(path).convert("RGB") as image:
        points: list[tuple[int, int]] = []
        for y in range(image.height):
            for x in range(image.width):
                pixel = cast(tuple[int, int, int], image.getpixel((x, y)))
                if color_kind(pixel) == kind:
                    points.append((x, y))
        return points


def color_bbox(path: Path, kind: str) -> tuple[int, int, int, int]:
    points = color_points(path, kind)
    assert len(points) > 50, (kind, len(points), path)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def render(source: Path, camera: str, look_at: str, output: Path) -> None:
    proc = subprocess.run(
        [
            str(RHR),
            "scene",
            str(source),
            "--viewport=480x360",
            f"--camera={camera}",
            f"--look-at={look_at}",
            "--fov=50",
            "--out",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def render_authored(source: Path, output: Path) -> None:
    proc = subprocess.run(
        [
            str(RHR),
            "scene",
            str(source),
            "--viewport=480x360",
            "--out",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-scene-foundation-") as directory:
        tmp = Path(directory)
        emitted = tmp / "foundation.json"
        emit_proc = subprocess.run(
            [str(RHR), "ir", str(FIXTURE), "--out", str(emitted)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert emit_proc.returncode == 0, emit_proc.stderr

        ir = json.loads(emitted.read_text())
        parts = find_nodes(ir["roots"][0], "Part") + find_nodes(ir["roots"][0], "WedgePart")
        names = {node["name"] for node in parts}
        assert {"FarBlue", "NearRed", "RotatedYellow", "Ball", "Cylinder"} <= names, names
        assert "GreenWedge" in {node["name"] for node in find_nodes(ir["roots"][0], "WedgePart")}

        dump_proc = subprocess.run(
            [str(RHR), "scene-dump", str(emitted)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert dump_proc.returncode == 0, dump_proc.stderr
        dump = json.loads(dump_proc.stdout)
        assert len(dump["parts"]) == 6, dump["parts"]
        assert len(dump["cameras"]) == 1, dump["cameras"]
        assert dump["bounds"] is not None

        views = {
            "front": ("0,4,16", "0,0,0"),
            "iso": ("14,10,14", "0,0,0"),
            "left": ("-16,4,0", "0,0,0"),
            "top": ("0,16,0", "0,0,0"),
        }
        outputs: dict[str, Path] = {}
        for name, (camera, look_at) in views.items():
            output = tmp / f"foundation-{name}.png"
            render(emitted, camera, look_at, output)
            outputs[name] = output
            for kind in ("red", "blue", "green", "yellow", "cyan", "magenta"):
                assert len(color_points(output, kind)) > 50, (name, kind)

        authored = tmp / "foundation-authored.png"
        render_authored(emitted, authored)
        assert authored.read_bytes() == outputs["front"].read_bytes(), "authored camera differs from explicit camera"

        front_red = color_bbox(outputs["front"], "red")
        front_blue = color_bbox(outputs["front"], "blue")
        assert (
            front_blue[0] <= front_red[0]
            and front_blue[1] <= front_red[1]
            and front_blue[2] >= front_red[2]
            and front_blue[3] >= front_red[3]
        ), (front_red, front_blue)

        repeat = tmp / "foundation-front-repeat.png"
        render(emitted, *views["front"], repeat)
        assert outputs["front"].read_bytes() == repeat.read_bytes(), "foundation render is not deterministic"
        assert outputs["front"].read_bytes() != outputs["iso"].read_bytes()
        assert outputs["front"].read_bytes() != outputs["left"].read_bytes()
        assert outputs["front"].read_bytes() != outputs["top"].read_bytes()

        print(
            "scene foundation: "
            f"front-red={len(color_points(outputs['front'], 'red'))}, "
            f"front-blue={len(color_points(outputs['front'], 'blue'))}, "
            f"front-occlusion-bbox={front_red} inside {front_blue}, "
            f"views={len(outputs)} deterministic"
        )


if __name__ == "__main__":
    main()
