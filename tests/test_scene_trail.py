#!/usr/bin/env python3
"""Linear-motion Trail baseline uses captured velocity and Trail sequences."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = ROOT / "bin" / "rhr"
FIXTURE = ROOT / "tests" / "fixtures" / "trail_motion.rbxmx"


def find_node(node: dict, class_name: str) -> dict | None:
    if node.get("className") == class_name:
        return node
    for child in node.get("children", []):
        found = find_node(child, class_name)
        if found is not None:
            return found
    return None


def red_bbox(path: Path) -> tuple[int, int, int, int] | None:
    with Image.open(path).convert("RGB") as image:
        pixels = image.load()
        points: list[tuple[int, int]] = []
        for y in range(image.height):
            for x in range(image.width):
                red, green, blue = (int(channel) for channel in pixels[x, y])
                if red > 140 and red > green * 2 and red > blue * 2:
                    points.append((x, y))
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def render(source: Path, output: Path) -> None:
    proc = subprocess.run(
        [
            str(RHR), "scene", str(source), "--viewport", "320x240",
            "--camera", "0,0,-20", "--look-at", "0,0,0", "--fov", "45",
            "--out", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rhr-trail-") as directory:
        tmp = Path(directory)
        emitted = tmp / "trail-emitted.json"
        emit_proc = subprocess.run(
            [str(RHR), "ir", str(FIXTURE), "--out", str(emitted)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert emit_proc.returncode == 0, emit_proc.stderr
        emitted_root = json.loads(emitted.read_text())["roots"][0]
        emitted_trail = find_node(emitted_root, "Trail")
        emitted_mover = find_node(emitted_root, "Part")
        assert emitted_trail is not None
        assert emitted_mover is not None
        emitted_props = emitted_trail["props"]
        emitted_mover_props = emitted_mover["props"]
        assert emitted_props["Attachment0"] == "TrailScene.Mover.A0"
        assert emitted_props["Attachment1"] == "TrailScene.Mover.A1"
        assert emitted_mover_props["AssemblyLinearVelocity"] == {"X": 4, "Y": 0, "Z": 0, "_t": "Vector3"}
        assert emitted_props["WidthScale"]["keypoints"][0]["Value"] == 0.25
        assert emitted_props["FaceCamera"] is True

        base_ir = json.loads(emitted.read_text())
        source = tmp / "trail.json"
        source.write_text(json.dumps(base_ir))
        output = tmp / "trail.png"
        render(source, output)
        bbox = red_bbox(output)
        assert bbox is not None, "velocity-backed FaceCamera trail produced no red pixels"
        assert bbox[2] - bbox[0] > 20, bbox
        assert bbox[3] - bbox[1] > 4, bbox

        dump_proc = subprocess.run(
            [str(RHR), "scene-dump", str(source)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert dump_proc.returncode == 0, dump_proc.stderr
        dump = json.loads(dump_proc.stdout)
        assert dump["unsupportedVisualClasses"] == {}, dump
        assert dump["trails"][0]["historySource"] == "AssemblyLinearVelocity", dump["trails"]
        assert dump["trails"][0]["supported"] is True

        short_ir = json.loads(json.dumps(base_ir))
        short_trail = find_node(short_ir["roots"][0], "Trail")
        assert short_trail is not None
        short_trail["props"]["Lifetime"] = 0.5
        short_source = tmp / "trail-short.json"
        short_source.write_text(json.dumps(short_ir))
        short_output = tmp / "trail-short.png"
        render(short_source, short_output)
        short_bbox = red_bbox(short_output)
        assert short_bbox is not None, "short trail produced no red pixels"
        assert bbox[2] - bbox[0] > short_bbox[2] - short_bbox[0] + 8, (bbox, short_bbox)

        no_face_ir = json.loads(json.dumps(base_ir))
        no_face_trail = find_node(no_face_ir["roots"][0], "Trail")
        assert no_face_trail is not None
        no_face_trail["props"]["FaceCamera"] = False
        no_face_source = tmp / "trail-no-face.json"
        no_face_source.write_text(json.dumps(no_face_ir))
        no_face_output = tmp / "trail-no-face.png"
        render(no_face_source, no_face_output)
        with Image.open(output).convert("RGB") as face_image, Image.open(no_face_output).convert("RGB") as no_face_image:
            changed = sum(
                1
                for pixel in ImageChops.difference(face_image, no_face_image).get_flattened_data()
                if pixel != (0, 0, 0)
            )
        assert changed > 100, changed

        fade_ir = json.loads(json.dumps(base_ir))
        fade_trail = find_node(fade_ir["roots"][0], "Trail")
        assert fade_trail is not None
        fade_keypoints = fade_trail["props"]["Transparency"]["keypoints"]
        fade_keypoints[0]["Value"] = 0
        fade_keypoints[-1]["Value"] = 1
        fade_source = tmp / "trail-fade.json"
        fade_source.write_text(json.dumps(fade_ir))
        fade_output = tmp / "trail-fade.png"
        render(fade_source, fade_output)
        with Image.open(fade_output).convert("RGB") as fade_image:
            fade_pixels = fade_image.load()
            background_red = int(fade_pixels[0, 0][0])
            tip_red = int(fade_pixels[170, 119][0]) - background_red
            tail_red = int(fade_pixels[210, 119][0]) - background_red
        assert tip_red > tail_red + 20, (tip_red, tail_red)

    print(
        f"scene trail: bbox={bbox}, short_bbox={short_bbox}, "
        f"face-mode changed={changed}, fade-tip/tail={tip_red}/{tail_red}"
    )


if __name__ == "__main__":
    main()
