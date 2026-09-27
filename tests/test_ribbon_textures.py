#!/usr/bin/env python3
"""Beam and Trail textures run the way Studio draws them.

Measured in Studio with an arrow image (tip at the image's bottom) on a Beam and on a
moving Trail:

- Beam: the image's top is at Attachment0, so the arrows point toward Attachment1.
  `TextureSpeed` scrolls it toward Attachment1, one whole texture per cycle
  (0.1 cycles/s moved it 0.72 of a texture in 7.2 s). RHR used to draw it upside
  down and still.
- Trail: the image's top is at the attachments (the newest end). In `Wrap` mode a
  whole tile starts there, as the tiles stay put relative to the attachments; RHR
  used to start them at the oldest end.
- A part's velocity is saved in files under its old name, `Velocity`; RHR used to
  miss it, so trails from real files were never drawn.

The test image is red on its top half and blue on its bottom half.

    python tests/test_ribbon_textures.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RHR = [sys.executable, "-m", "rhr"]
ASSET_ID = "1000002"
TRAIL_FIXTURE = ROOT / "tests" / "fixtures" / "trail_motion.rbxmx"
IDENTITY = {"R00": 1, "R01": 0, "R02": 0, "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1}
WHITE = {"_t": "ColorSequence", "keypoints": [
    {"Time": 0, "Value": {"_t": "Color3", "R": 1, "G": 1, "B": 1}},
    {"Time": 1, "Value": {"_t": "Color3", "R": 1, "G": 1, "B": 1}},
]}
OPAQUE = {"_t": "NumberSequence", "keypoints": [
    {"Time": 0, "Value": 0, "Envelope": 0}, {"Time": 1, "Value": 0, "Envelope": 0},
]}


def marker_image(path: Path) -> None:
    image = Image.new("RGB", (64, 64), (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, 64, 32))
    image.save(path)


def is_red(pixel) -> bool:
    return pixel[0] > 150 and pixel[1] < 90 and pixel[2] < 90


def is_blue(pixel) -> bool:
    return pixel[2] > 150 and pixel[0] < 90 and pixel[1] < 90


def centroid_x(image: Image.Image, test) -> float | None:
    pixels = image.load()
    xs = [x for y in range(image.height) for x in range(image.width) if test(pixels[x, y])]
    return sum(xs) / len(xs) if xs else None


def part(name: str, x: float, children: list[dict], extra: dict | None = None) -> dict:
    return {
        "className": "Part", "name": name, "children": children,
        "props": {
            "CFrame": {"_t": "CFrame", "X": x, "Y": 0, "Z": 0, **IDENTITY},
            "Size": {"_t": "Vector3", "X": 0.2, "Y": 0.2, "Z": 0.2},
            "Transparency": 1, "Anchored": True, **(extra or {}),
        },
    }


def attachment(name: str, y: float = 0, children: list[dict] | None = None) -> dict:
    return {"className": "Attachment", "name": name, "children": children or [],
            "props": {"CFrame": {"_t": "CFrame", "X": 0, "Y": y, "Z": 0, **IDENTITY}}}


def workspace(children: list[dict]) -> dict:
    return {"sourcePath": "ribbon-test", "roots": [
        {"className": "Workspace", "name": "Workspace", "props": {}, "children": children}]}


def beam_scene(speed: float) -> dict:
    # Attachment0 on the left (world -X), Attachment1 on the right; the camera looks
    # from +Z, so world +X is screen right.
    beam = {"className": "Beam", "name": "Beam", "children": [], "props": {
        "Attachment0": "Workspace.P0.A0", "Attachment1": "Workspace.P1.A1",
        "Width0": 2, "Width1": 2, "Segments": 10, "FaceCamera": True,
        "Texture": f"rbxassetid://{ASSET_ID}", "TextureMode": {"_t": "EnumItem", "name": "Stretch"},
        "TextureLength": 1, "TextureSpeed": speed, "Color": WHITE, "Transparency": OPAQUE,
    }}
    return workspace([part("P0", -6, [attachment("A0", 0, [beam])]), part("P1", 6, [attachment("A1")])])


def trail_scene() -> dict:
    # Moving +X at 4 studs/s for a 3 s lifetime: a trail from x = -6 (oldest) to
    # x = 6 (newest), tiled every 5 studs.
    trail = {"className": "Trail", "name": "Trail", "children": [], "props": {
        "Attachment0": "Workspace.Mover.A0", "Attachment1": "Workspace.Mover.A1",
        "Lifetime": 3, "FaceCamera": False,
        "Texture": f"rbxassetid://{ASSET_ID}", "TextureMode": {"_t": "EnumItem", "name": "Wrap"},
        "TextureLength": 5, "Color": WHITE, "Transparency": OPAQUE,
    }}
    velocity = {"AssemblyLinearVelocity": {"_t": "Vector3", "X": 4, "Y": 0, "Z": 0}}
    return workspace([part("Mover", 6, [attachment("A0", 1), attachment("A1", -1), trail], velocity)])


def render(ir: dict, tmp: Path, name: str, textures: Path, extra: list[str] | None = None) -> Image.Image:
    source = tmp / f"{name}.json"
    source.write_text(json.dumps(ir), encoding="utf-8")
    out = tmp / f"{name}.png"
    proc = subprocess.run(
        [*RHR, "scene", str(source), "--viewport", "320x160", "--camera", "0,0,14", "--look-at", "0,0,0",
         "--fov", "60", "--texture-dir", str(textures), "--out", str(out), *(extra or [])],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return Image.open(out).convert("RGB")


def screen_x(world_x: float, image: Image.Image) -> int:
    # Camera 14 studs away with a 60 degree vertical field of view.
    half_height = 14 * 0.5773502691896257
    return round(image.width / 2 + world_x / half_height * image.height / 2)


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="rhr-ribbons-") as directory:
        tmp = Path(directory)
        textures = tmp / "textures"
        textures.mkdir()
        marker_image(textures / f"{ASSET_ID}.png")

        still = render(beam_scene(0), tmp, "beam-still", textures)
        red, blue = centroid_x(still, is_red), centroid_x(still, is_blue)
        ok = red is not None and blue is not None and red < blue
        print(f"  {'ok  ' if ok else 'FAIL'} beam image top at Attachment0: red x={red}, blue x={blue}")
        if not ok:
            failures.append(f"beam: red {red} should be left of blue {blue}")

        # A quarter cycle moves the red half a quarter of the beam toward Attachment1.
        moved = render(beam_scene(0.25), tmp, "beam-moved", textures, ["--effect-time", "1"])
        red_moved = centroid_x(moved, is_red)
        quarter = screen_x(3, still) - screen_x(0, still)
        ok = red is not None and red_moved is not None and abs((red_moved - red) - quarter) < quarter * 0.3
        print(f"  {'ok  ' if ok else 'FAIL'} beam TextureSpeed: red moved {None if red_moved is None or red is None else red_moved - red:.1f} px, expected {quarter}")
        if not ok:
            failures.append(f"beam TextureSpeed: red {red} -> {red_moved}, expected +{quarter} px")

        trail = render(trail_scene(), tmp, "trail", textures)
        pixels = trail.load()
        row = trail.height // 2
        # Tiles from the newest end: x 6..3.5 red, 3.5..1 blue.
        near_new, further = pixels[screen_x(5, trail), row], pixels[screen_x(2, trail), row]
        ok = is_red(near_new) and is_blue(further)
        print(f"  {'ok  ' if ok else 'FAIL'} trail Wrap tiles start at the attachments: x=5 {near_new}, x=2 {further}")
        if not ok:
            failures.append(f"trail: x=5 {near_new} should be red, x=2 {further} blue")

        # Studio saves the part's velocity as `Velocity`.
        legacy = tmp / "trail-legacy.rbxmx"
        legacy.write_text(
            TRAIL_FIXTURE.read_text(encoding="utf-8").replace('name="AssemblyLinearVelocity"', 'name="Velocity"'),
            encoding="utf-8",
        )
        ir_out = tmp / "trail-legacy.json"
        proc = subprocess.run([*RHR, "ir", str(legacy), "--out", str(ir_out)],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
        roots = json.loads(ir_out.read_text(encoding="utf-8"))["roots"]
        stack, velocity = list(roots), None
        while stack:
            node = stack.pop()
            if node.get("className") == "Part":
                velocity = node.get("props", {}).get("AssemblyLinearVelocity")
            stack.extend(node.get("children", []))
        ok = velocity == {"X": 4, "Y": 0, "Z": 0, "_t": "Vector3"}
        print(f"  {'ok  ' if ok else 'FAIL'} velocity saved as Velocity: {velocity}")
        if not ok:
            failures.append(f"legacy Velocity not read: {velocity}")
    assert not failures, failures
    print("ribbon textures: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
