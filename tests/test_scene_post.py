#!/usr/bin/env python3
"""Post-processing: Neon glows past its edges only when it is bright (as in Studio at
high quality), and ColorCorrectionEffect changes the picture.

    python tests/test_scene_post.py
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
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def part(name: str, x: float, material: str, rgb: tuple[float, float, float]) -> dict:
    return {
        "className": "Part",
        "name": name,
        "props": {
            "CFrame": {"_t": "CFrame", "X": x, "Y": 0, "Z": 0, "R00": 1, "R01": 0, "R02": 0,
                       "R10": 0, "R11": 1, "R12": 0, "R20": 0, "R21": 0, "R22": 1},
            "Size": {"_t": "Vector3", "X": 2, "Y": 2, "Z": 2},
            "Color": {"_t": "Color3", "R": rgb[0], "G": rgb[1], "B": rgb[2]},
            "Material": {"_t": "EnumItem", "enum": "Enum.Material", "name": material, "value": 0},
            "Shape": {"_t": "EnumItem", "enum": "Enum.PartType", "name": "Block", "value": 1},
        },
        "children": [],
    }


def write_ir(path: Path, effects: list[dict]) -> None:
    parts = [
        part("BrightNeon", -3.0, "Neon", (1.0, 0.5, 0.0)),   # orange: past white, glows
        part("DimNeon", 3.0, "Neon", (0.3, 0.15, 0.45)),     # dim purple: no glow
    ]
    backdrop = part("Backdrop", 0.0, "SmoothPlastic", (0.05, 0.05, 0.05))
    backdrop["props"]["CFrame"]["Z"] = -3
    backdrop["props"]["Size"] = {"_t": "Vector3", "X": 40, "Y": 20, "Z": 1}
    parts.append(backdrop)
    lighting = {"className": "Lighting", "name": "Lighting",
                "props": {"Brightness": 0, "Ambient": {"_t": "Color3", "R": 0, "G": 0, "B": 0},
                          "OutdoorAmbient": {"_t": "Color3", "R": 0, "G": 0, "B": 0}},
                "children": effects}
    path.write_text(json.dumps({"sourcePath": "post-test", "roots": [
        {"className": "Workspace", "name": "Workspace", "props": {}, "children": parts},
        lighting,
    ]}))


def render(ir: Path, out: Path) -> None:
    proc = subprocess.run([*RHR, "scene", str(ir), "--out", str(out), "--viewport", "400x200",
                           "--camera", "0,0,9", "--look-at", "0,0,0", "--flat-materials"],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr


def ring_brightness(image: Image.Image, cx: int, cy: int, inner: int, outer: int) -> float:
    """Mean brightness in a square ring around (cx, cy): just outside a part's edge."""
    total = count = 0
    for y in range(cy - outer, cy + outer):
        for x in range(cx - outer, cx + outer):
            if max(abs(x - cx), abs(y - cy)) < inner:
                continue
            r, g, b = image.getpixel((x, y))
            total += r + g + b
            count += 1
    return total / count / 3


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rhr-post-") as directory:
        tmp = Path(directory)
        plain_ir, cc_ir = tmp / "plain.json", tmp / "cc.json"
        write_ir(plain_ir, [])
        write_ir(cc_ir, [{"className": "ColorCorrectionEffect", "name": "Grey",
                          "props": {"Saturation": -1, "Enabled": True}, "children": []}])
        plain, cc = tmp / "plain.png", tmp / "cc.png"
        render(plain_ir, plain)
        render(cc_ir, cc)
        with Image.open(plain).convert("RGB") as image:
            # Part centres: the camera at z=9 with FOV 70 sees about 12.6 studs across
            # 200 px of height, so 1 stud is ~16 px; parts are 2 studs (~32 px) wide.
            bright = ring_brightness(image, 200 - 48, 100, 20, 30)
            dim = ring_brightness(image, 200 + 48, 100, 20, 30)
            centre = image.getpixel((200 - 48, 100))
        check("a bright Neon part glows past its edge", bright > dim + 8, f"ring {bright:.1f} vs {dim:.1f}")
        check("Neon is drawn brighter than its colour (clipped)", centre[0] >= 250 and centre[1] >= 200,
              repr(centre))
        with Image.open(cc).convert("RGB") as image:
            r, g, b = image.getpixel((200 - 48, 100))
        check("ColorCorrectionEffect Saturation -1 turns the picture grey", max(r, g, b) - min(r, g, b) < 12,
              repr((r, g, b)))
    print("scene post: ok" if not failures else f"scene post: {len(failures)} failed")
    return 1 if failures else 0


def test_main():
    from _harness import run_main

    run_main(main)


if __name__ == "__main__":
    raise SystemExit(main())
