#!/usr/bin/env python3
"""Static Beam baseline resolves Attachment references and draws visible geometry."""

from __future__ import annotations

import sys
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
FIXTURE = ROOT / "tests" / "fixtures" / "beam_transparency.rbxmx"


def find_node(node: dict, class_name: str) -> dict | None:
    if node.get("className") == class_name:
        return node
    for child in node.get("children", []):
        found = find_node(child, class_name)
        if found is not None:
            return found
    return None


def render_scene(source: Path, output: Path) -> None:
    proc = subprocess.run(
        [
            *RHR, "scene", str(source), "--viewport", "320x240",
            "--camera", "0,0,-14", "--look-at", "0,0,0", "--out", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def part(name: str, x: float, child: dict | None = None) -> dict:
    return {
        "className": "Part",
        "name": name,
        "props": {
            "CFrame": {
                "_t": "CFrame", "X": x, "Y": 0, "Z": 0,
                "R00": 1, "R01": 0, "R02": 0,
                "R10": 0, "R11": 1, "R12": 0,
                "R20": 0, "R21": 0, "R22": 1,
            },
            "Size": {"_t": "Vector3", "X": 0.4, "Y": 0.4, "Z": 0.4},
            "Color": {"_t": "Color3", "R": 0.1, "G": 0.1, "B": 0.1},
            "Transparency": 1,
            "Material": {"_t": "EnumItem", "name": "Plastic", "value": 256},
            "Shape": {"_t": "EnumItem", "name": "Block", "value": 1},
        },
        "children": [child] if child else [],
    }


def attachment(name: str, beam: dict | None = None, *, rotated: bool = False) -> dict:
    props = {"Position": {"_t": "Vector3", "X": 0, "Y": 0, "Z": 0}}
    if rotated:
        # Rotate the attachment's local X axis up. Roblox Beam uses each
        # attachment's local X axis for CurveSize control points.
        props["CFrame"] = {
            "_t": "CFrame", "X": 0, "Y": 0, "Z": 0,
            "R00": 0, "R01": -1, "R02": 0,
            "R10": 1, "R11": 0, "R12": 0,
            "R20": 0, "R21": 0, "R22": 1,
        }
    return {
        "className": "Attachment",
        "name": name,
        "props": props,
        "children": [beam] if beam else [],
    }


def main() -> None:
    beam = {
        "className": "Beam",
        "name": "Link",
        "props": {
            "Attachment0": "Workspace.P0.A0",
            "Attachment1": "Workspace.P1.A1",
            "Width0": 0.7,
            "Width1": 0.7,
            "CurveSize0": 0,
            "CurveSize1": 0,
            "Segments": 10,
            "Enabled": True,
            "Brightness": 1,
            "Color": {"_t": "ColorSequence", "keypoints": [
                {"Time": 0, "Value": {"_t": "Color3", "R": 1, "G": 0.1, "B": 0.05}},
                {"Time": 1, "Value": {"_t": "Color3", "R": 1, "G": 0.1, "B": 0.05}},
            ]},
            "Transparency": {"_t": "NumberSequence", "keypoints": [
                {"Time": 0, "Value": 0, "Envelope": 0},
                {"Time": 1, "Value": 0, "Envelope": 0},
            ]},
        },
        "children": [],
    }
    ir = {
        "sourcePath": "beam-test",
        "roots": [{
            "className": "Workspace",
            "name": "Workspace",
            "props": {},
            "children": [
                part("P0", -4, attachment("A0", beam)),
                part("P1", 4, attachment("A1")),
            ],
        }],
    }

    with tempfile.TemporaryDirectory(prefix="rhr-beam-") as directory:
        tmp = Path(directory)
        src = tmp / "beam.json"
        src.write_text(json.dumps(ir))
        out = tmp / "beam.png"
        proc = subprocess.run(
            [*RHR, "scene", str(src), "--viewport", "320x240",
             "--camera", "0,0,-14", "--look-at", "0,0,0", "--out", str(out)],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        red = 0
        with Image.open(out).convert("RGB") as image:
            for r, g, b in image.get_flattened_data():
                if r > 140 and r > g * 2 and r > b * 2:
                    red += 1
        assert red > 500, red

        proc = subprocess.run(
            [*RHR, "scene-dump", str(src)],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        dump = json.loads(proc.stdout)
        assert dump["unsupportedVisualClasses"] == {}
        assert dump["beams"][0]["attachment0"] == "Workspace/P0/A0"
        assert dump["beams"][0]["attachment1"] == "Workspace/P1/A1"
        # Effects are no longer "experimental": they were checked against Studio.
        assert "Beam" not in dump["experimental"], dump["experimental"]

        # CurveSize control points use each attachment's local X axis. The
        # pre-fix cylinder path renders this curved and straight case identically.
        curved = json.loads(json.dumps(beam))
        curved["props"]["CurveSize0"] = 4
        curved["props"]["CurveSize1"] = 4
        curved["props"]["Segments"] = 20
        curved["props"]["FaceCamera"] = True
        curved_ir = {
            "sourcePath": "beam-curve-test",
            "roots": [{
                "className": "Workspace",
                "name": "Workspace",
                "props": {},
                "children": [
                    part("P0", -4, attachment("A0", curved, rotated=True)),
                    part("P1", 4, attachment("A1", rotated=True)),
                ],
            }],
        }
        curved_src = tmp / "beam-curved.json"
        curved_out = tmp / "beam-curved.png"
        curved_src.write_text(json.dumps(curved_ir))
        proc = subprocess.run(
            [*RHR, "scene", str(curved_src), "--viewport", "320x240",
             "--camera", "0,0,-14", "--look-at", "0,0,0", "--out", str(curved_out)],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        with Image.open(out).convert("RGB") as straight_image, Image.open(curved_out).convert("RGB") as curved_image:
            diff = ImageChops.difference(straight_image, curved_image)
            changed = sum(1 for pixel in diff.get_flattened_data() if pixel != (0, 0, 0))
        assert changed > 500, changed

        emitted = tmp / "beam-emitted.json"
        emit_proc = subprocess.run(
            [*RHR, "ir", str(FIXTURE), "--out", str(emitted)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert emit_proc.returncode == 0, emit_proc.stderr
        emitted_ir = json.loads(emitted.read_text())
        emitted_beam = find_node(emitted_ir["roots"][0], "Beam")
        assert emitted_beam is not None
        assert emitted_beam["props"]["Attachment0"] == "BeamScene.P0.A0"
        assert emitted_beam["props"]["Attachment1"] == "BeamScene.P1.A1"

        emitted_source = tmp / "beam-emitted-source.json"
        emitted_source.write_text(json.dumps(emitted_ir))
        emitted_output = tmp / "beam-emitted.png"
        render_scene(emitted_source, emitted_output)

        fade_ir = json.loads(json.dumps(emitted_ir))
        fade_beam = find_node(fade_ir["roots"][0], "Beam")
        assert fade_beam is not None
        fade_keypoints = fade_beam["props"]["Transparency"]["keypoints"]
        fade_keypoints[0]["Value"] = 0
        fade_keypoints[-1]["Value"] = 1
        fade_source = tmp / "beam-fade.json"
        fade_source.write_text(json.dumps(fade_ir))
        fade_output = tmp / "beam-fade.png"
        render_scene(fade_source, fade_output)
        with Image.open(fade_output).convert("RGB") as fade_image:
            fade_pixels = fade_image.load()
            background_red = int(fade_pixels[0, 0][0])
            tip_red = int(fade_pixels[200, 120][0]) - background_red
            tail_red = int(fade_pixels[120, 120][0]) - background_red
        assert tip_red > tail_red + 40, (tip_red, tail_red)

    print(
        f"scene beam: red pixels={red}, curved-vs-straight changed={changed}, "
        f"fade-tip/tail={tip_red}/{tail_red}"
    )


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    main()
