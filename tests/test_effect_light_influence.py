#!/usr/bin/env python3
"""LightInfluence lights particles, Beams and Trails the way Studio does.

Measured in Studio with flat white particles and beams: LightInfluence L blends the
effect's Brightness toward the scene's light with weight sqrt(L). With no light at all
(Brightness 0, black ambients) L = 1 draws the effect black (it still covers what is
behind it) and L = 0.5 keeps about 30% of the light; in sun-only daylight (Brightness 2) the scene's light equals an unlit effect's,
so L changes nothing. RHR used to draw every effect as if L were 0.

    python tests/test_effect_light_influence.py
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
ASSET_ID = "1000003"
IDENTITY = {"R00": 1, "R01": 0, "R02": 0, "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1}
WHITE = {"_t": "ColorSequence", "keypoints": [
    {"Time": 0, "Value": {"_t": "Color3", "R": 1, "G": 1, "B": 1}},
    {"Time": 1, "Value": {"_t": "Color3", "R": 1, "G": 1, "B": 1}},
]}
OPAQUE = {"_t": "NumberSequence", "keypoints": [
    {"Time": 0, "Value": 0, "Envelope": 0}, {"Time": 1, "Value": 0, "Envelope": 0},
]}
BLACK = {"_t": "Color3", "R": 0, "G": 0, "B": 0}
# Beams at LightInfluence 0, 0.5, 1 (rows at y = 4, 1, -2) and a particle at 1 (y = -5).
BEAM_ROWS = {0: 4, 0.5: 1, 1: -2}
PARTICLE_Y = -5


def part(name: str, x: float, y: float, children: list[dict]) -> dict:
    return {"className": "Part", "name": name, "children": children, "props": {
        "CFrame": {"_t": "CFrame", "X": x, "Y": y, "Z": 0, **IDENTITY},
        "Size": {"_t": "Vector3", "X": 0.2, "Y": 0.2, "Z": 0.2}, "Transparency": 1, "Anchored": True}}


def attachment(name: str, children: list[dict] | None = None) -> dict:
    return {"className": "Attachment", "name": name, "children": children or [],
            "props": {"CFrame": {"_t": "CFrame", "X": 0, "Y": 0, "Z": 0, **IDENTITY}}}


def scene(brightness: float) -> dict:
    children = []
    for index, (influence, y) in enumerate(BEAM_ROWS.items()):
        beam = {"className": "Beam", "name": f"Beam{index}", "children": [], "props": {
            "Attachment0": f"Workspace.L{index}.A0", "Attachment1": f"Workspace.R{index}.A1",
            "Width0": 2, "Width1": 2, "FaceCamera": True, "Brightness": 1, "LightInfluence": influence,
            "TextureSpeed": 0, "Texture": f"rbxassetid://{ASSET_ID}", "Color": WHITE, "Transparency": OPAQUE,
        }}
        children += [part(f"L{index}", -5, y, [attachment("A0", [beam])]), part(f"R{index}", 5, y, [attachment("A1")])]
    emitter = {"className": "ParticleEmitter", "name": "Lit", "children": [], "props": {
        "Texture": f"rbxassetid://{ASSET_ID}", "Enabled": True, "Rate": 20,
        "Lifetime": {"_t": "NumberRange", "Min": 5, "Max": 5}, "Speed": {"_t": "NumberRange", "Min": 0, "Max": 0},
        "Size": {"_t": "NumberSequence", "keypoints": [{"Time": 0, "Value": 1, "Envelope": 0}, {"Time": 1, "Value": 1, "Envelope": 0}]},
        "Transparency": OPAQUE, "Color": WHITE, "Brightness": 1, "LightInfluence": 1, "LightEmission": 0,
    }}
    children.append(part("Emitter", 0, PARTICLE_Y, [emitter]))
    lighting = {"className": "Lighting", "name": "Lighting", "children": [], "props": {
        "Ambient": BLACK, "OutdoorAmbient": BLACK, "Brightness": brightness, "ClockTime": 14, "GlobalShadows": False}}
    return {"sourcePath": "light-influence-test", "roots": [
        lighting, {"className": "Workspace", "name": "Workspace", "props": {}, "children": children}]}


def render(ir: dict, tmp: Path, name: str, textures: Path) -> Image.Image:
    source = tmp / f"{name}.json"
    source.write_text(json.dumps(ir), encoding="utf-8")
    out = tmp / f"{name}.png"
    proc = subprocess.run(
        [*RHR, "scene", str(source), "--viewport", "240x240", "--camera", "0,0,20", "--look-at", "0,0,0",
         "--fov", "40", "--effect-time", "2", "--texture-dir", str(textures), "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return Image.open(out).convert("RGB")


def level(image: Image.Image, y: float) -> float:
    # Mean brightness of a small patch at world (0, y).
    half = 20 * 0.36397  # tan(20 degrees)
    row = round(image.height / 2 - y / half * image.height / 2)
    column = image.width // 2
    pixels = image.load()
    patch = [sum(pixels[column + dx, row + dy]) / 3 for dx in range(-3, 4) for dy in range(-1, 2)]
    return sum(patch) / len(patch)


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="rhr-light-influence-") as directory:
        tmp = Path(directory)
        textures = tmp / "textures"
        textures.mkdir()
        Image.new("RGB", (32, 32), (255, 255, 255)).save(textures / f"{ASSET_ID}.png")

        dark = render(scene(0), tmp, "dark", textures)
        unlit, half, lit, particle = (level(dark, y) for y in (*BEAM_ROWS.values(), PARTICLE_Y))
        checks = [
            ("dark: unlit beam bright", unlit > 200),
            ("dark: half-lit beam dimmer than unlit", 60 < half < unlit - 40),
            ("dark: fully lit beam black", lit < 10),
            ("dark: fully lit particle black", particle < 10),
        ]
        print(f"  dark levels: unlit {unlit:.0f}, half {half:.0f}, lit {lit:.0f}, particle {particle:.0f}")

        day = render(scene(2), tmp, "day", textures)
        unlit_d, half_d, lit_d, particle_d = (level(day, y) for y in (*BEAM_ROWS.values(), PARTICLE_Y))
        checks += [
            ("day: lit beam as bright as unlit", abs(lit_d - unlit_d) < 8 and abs(half_d - unlit_d) < 8),
            ("day: lit particle bright", particle_d > 150),
        ]
        print(f"  day levels: unlit {unlit_d:.0f}, half {half_d:.0f}, lit {lit_d:.0f}, particle {particle_d:.0f}")
        for label, ok in checks:
            print(f"  {'ok  ' if ok else 'FAIL'} {label}")
            if not ok:
                failures.append(label)
    assert not failures, failures
    print("effect LightInfluence: ok")
    return 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
